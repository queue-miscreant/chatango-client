#!/usr/bin/env python3
#client.py:
#		Client library with single-byte curses input
#		Uses a system of overlays, pulling input from
#		the topmost one.
#		Output is done not with curses display, but
#		various variations of print()

try:
	import curses
except ImportError:
	raise ImportError("ERROR WHILE IMPORTING CURSES, is this running on Windows cmd?")
import sys
if not sys.stdout.isatty(): #check if terminal
	raise IOError("This script is not intended to be piped")
from os import environ
from threading import Thread
from wcwidth import wcwidth
import traceback
import re
import time
#escape has delay typically
environ.setdefault('ESCDELAY', '25')

active = False
lastlinks = []
lasterr = None
#useful regexes --------------
WORD_RE = re.compile("[^ ]* ")
ANSI_ESC_RE = re.compile("\x1b"+r"\[[^A-z]*[A-z]")
LINK_RE = re.compile("(https?://.+?\\.[^\n` 　]+)[\n` 　]")
_LAST_COLOR_RE = re.compile("\x1b"+r"\[[^m]*3[^m]*[^m]*m")
_UP_TO_WORD_RE = re.compile('(.* )[^ ]+ *')
#if you're changing these I don't know what to say
#guessed terminal dimensions
DIM_X = 40
DIM_Y = 70
RESERVE_LINES = 3
#break if smaller than these
_MIN_X = 0
_MIN_Y = RESERVE_LINES
checkmins = lambda: DIM_X < _MIN_X or DIM_Y < _MIN_Y
def setmins(newx,newy):
	global _MIN_X,_MIN_Y
	_MIN_X=max(_MIN_X,newx)
	_MIN_Y=max(_MIN_Y,newy)
#------------------------------------------------------------------------------
#valid colors to add
_COLORS = ['black','red','green','yellow','blue','magenta','cyan','white','','none']
#0 = reverse; 1 = underline
_EFFECTS = ['\x1b[7m','\x1b[4m']
#storage for defined pairs
#		Normal/Normal	Red/White	Red		Green		Blue
_COLOR_PAIRS = ['\x1b[39;49m','\x1b[31;47m','\x1b[31;41m','\x1b[32;42m','\x1b[34;44m']
_NUM_PREDEFINED = len(_COLOR_PAIRS)
#clear formatting
CLEAR_FORMATTING = '\x1b[m'
#------------------------------------------------------------------------------
INDENT_LEN = 4
INDENT_STR = ""
#overlay formatting
CHAR_HSPACE = "─"
CHAR_VSPACE = "│"
CHAR_TOPS = "┌┐"
CHAR_BOTTOMS = "└┘"
CHAR_CURSOR = '\x1b[s'
#reload, newline, go up
CHAR_RETURN_CURSOR = '\x1b[u\n\x1b[A'
CHAR_COMMAND = "/"
#lambdas
BOX_TOP = lambda: CHAR_TOPS[0] + (CHAR_HSPACE * (DIM_X-2)) + CHAR_TOPS[1]
#just the number of spaces to justify
BOX_JUST = lambda x: DIM_X-2+sum([i.end(0)-i.start(0) for i in ANSI_ESC_RE.finditer(x)])
#formatted and sandwiched
BOX_PART = lambda x: CHAR_VSPACE + x.ljust(BOX_JUST(x)) + CHAR_VSPACE	
#sandwiched between verticals
BOX_NOFORM = lambda x: CHAR_VSPACE + x + CHAR_VSPACE
BOX_BOTTOM = lambda: CHAR_BOTTOMS[0] + (CHAR_HSPACE * (DIM_X-2)) + CHAR_BOTTOMS[1]
SELECTED = lambda x: _EFFECTS[0] + x + CLEAR_FORMATTING
def centered(string,width,isselected):
	pre = string.rjust((width+len(string))//2).ljust(width)
	if isselected: pre = SELECTED(pre)
	return pre
#------------------------------------------------------------------------------
#names of valid keys
_VALID_KEYNAMES = {
	'tab':		9
	,'enter':	10
	,'backspace':	127
}
#these keys point to another key
_KEY_LUT = {
	#curses redirects ctrl-h here for some reason
	curses.KEY_BACKSPACE:	127
	#numpad enter
	,curses.KEY_ENTER:	10
	#ctrl-m to ctrl-j (carriage return to line feed)
	#this really shouldn't be necessary, since curses does that
	,13:			10
					
}
for i in dir(curses):
	if "KEY_" in i:
		name = i[4:].lower()
		if name not in _VALID_KEYNAMES: #don't map KEY_BACKSPACE or KEY_ENTER
			_VALID_KEYNAMES[name] = getattr(curses,i)
#simplicity's sake
for i in range(32):
	#no, not +96 because that gives wrong characters for ^@ and ^_ (\x00 and \x1f)
	_VALID_KEYNAMES['^%s'%chr(i+64).lower()] = i
for i in range(32,256):
	_VALID_KEYNAMES[chr(i)] = i

class KeyException(Exception): pass

#we should be cloning one character to another
def cloneKey(fro,to):
	try:
		if isinstance(fro,str):
			fro = _VALID_KEYNAMES[fro]
		if isinstance(to,str):
			to = _VALID_KEYNAMES[to]
	except: raise KeyException("%s or %s is an invalid key name"%(fro,to))
	_KEY_LUT[fro] = to

#standard scrollable controls
def scrollablecontrol(scroll):
	return {
		127:			staticize(scroll.backspace)
		,curses.KEY_DC:		staticize(scroll.delchar)
		,curses.KEY_SHOME:	staticize(scroll.clear)
		,curses.KEY_RIGHT:	staticize2(scroll.movepos,1)
		,curses.KEY_LEFT:	staticize2(scroll.movepos,-1)
		,curses.KEY_UP:		lambda x: scroll.nexthist() or 1 #return 1
		,curses.KEY_DOWN:	lambda x: scroll.prevhist() or 1 #return 1
		,curses.KEY_HOME:	staticize(scroll.home)
		,curses.KEY_END:	staticize(scroll.end)
	}
#------------------------------------------------------------------------------
#conversions to and from hex strings ([255,255,255] <-> FFFFFF)
toHexColor = lambda rgb: ''.join([hex(i)[2:].rjust(2,'0') for i in rgb])
fromHexColor = lambda hexStr: [int(hexStr[2*i:2*i+2],16) for i in range(3)]

#------------------------------------------------------------------------------
#useful containers for certain contexts
colorers = []
commands = {}
filters = []
class link_opener:
	sites = {}
	lambdas = []
	lambdalut = []
#	__init__ is like a static __call__
	def __init__(self,client,link,forcelink=False):
		ext = extractext(link)
		if forcelink:
			getattr(self, 'default')(client,link)
			return

		if hasattr(self,ext):
			getattr(self, ext)(client,link,ext)
		else:
			for i,j in self.sites.items():
				if 1+link.find(i):
					j(client,link)
					return
			for i in range(len(self.lambdas)):
				if self.lambdas[i](link):
					self.lambdalut[i](client,link)
			getattr(self, 'default')(client,link)
	#raise exception if not overridden
	def default(*args):
		raise Exception("No regular link handler defined")

#look for the furthest / or ?
def extractext(link):
	ext = link[link.rfind('.')+1:]
	lenext = len(ext)
	slash = ext.find('/')+1 
	quest = ext.find('?')+1
	#yes this looks stupid, yes it works
	trim = quest and (slash and min(slash,quest) or quest) or slash
	if trim:
		ext = ext[:trim-1]
	return ext

#decorators for containers
def colorer(func):
	colorers.append(func)
def chatfilter(func):
	filters.append(func)
def command(commandname):
	def wrapper(func):
		commands[commandname] = func
	return wrapper
def opener(typ,pore = None):
	def wrap(func):
		if typ == 0:
			setattr(link_opener,'default',staticmethod(func))
		elif typ == 1 and pore is not None:
			setattr(link_opener,pore,staticmethod(func))
		elif typ == 2 and pore is not None:
			link_opener.sites[pore] = func
		elif typ == 3 and pore is not None:
			link_opener.lambdas.append(pore)
			link_opener.lambdalut.append(func)
		#allow stacking wrappers
		return func
	return wrap

#add links to a list
def parseLinks(raw):
	global lastlinks
	newLinks = []
	#look for whole word links starting with http:// or https://
	#don't add the same link twice
	for i in LINK_RE.findall(raw+" "):
		if i not in newLinks:
			newLinks.append(i)
	lastlinks += newLinks

@command('help')
def listcommands(cli,args):
	def select(self):
		new = commandOverlay(cli)
		new.text.clear()
		new.text.append(self.list[self.it])
		cli.replaceOverlay(new)

	commandsList = listOverlay(list(commands))
	commandsList.addKeys({
		'enter':select
	})
	return commandsList
	
#------------------------------------------------------------------------------
#COLORING METHODS

#exception raised when errors occur in this segment
class ColoringException(Exception): pass

def decolor(string):
	#replace all escapes with null string
	new = ANSI_ESC_RE.subn('',string)
	#only return the string
	return new[0]

#coloring objects contain a string and default color
class coloring:
	def __init__(self,string,default=None):
		self._str = string
		self.default = default
	def __repr__(self):
		return self._str
	def __getitem__(self,sliced):
		self._str = self._str[sliced]
		return self
	def __add__(self,other):
		self._str = self._str + other
		return self
	def __radd__(self,other):
		self._str = other + self._str
		return self
	#insert color at position p with color c
	def insertColor(self,p,c=-1,add = True):
		c = self.default if c == -1 else c
		try:
			c = type(c) != str and _COLOR_PAIRS[c + (add and _NUM_PREDEFINED)] or c 
		except IndexError:
			raise ColoringException("Foreground/Background pair not defined")
		self._str = self._str[:p] + c + self._str[p:]
		#return length of c to adjust tracker variables in colorers
		return len(c)
	#add effect to string (if test is true)
	def addEffect(self, number, test = True):
		self._str = (test and _EFFECTS[number] or "") + self._str
	#most recent color before end
	def findColor(self,end):
		lastcolor = {end-i.end(0):i.group(0) for i in _LAST_COLOR_RE.finditer(self._str) if (end-i.end(0))>=0}
		try:
			return lastcolor[min(lastcolor)]
		except:
			return ''
	def ljust(self,spacing):
		self._str = self._str.ljust(spacing)

def definepair(fore, bold = None, back = 'none'):
	global _COLOR_PAIRS
	pair = '\x1b[3%d' % _COLORS.index(fore);
	pair += bold and ";1" or ";22"
	pair += ';4%d' % _COLORS.index(back) or ""
	_COLOR_PAIRS.append(pair+'m')

#clear formatting (reverse, etc) after each message
@colorer
def removeFormatting(msg,*args):
	msg + CLEAR_FORMATTING

#------------------------------------------------------------------------------
#DISPLAY FITTING

#column width of string
def strlen(string):
	#not in an escape sequence
	escape = False
	a = 0
	for i in string:
		temp = (i == '\x1b') or escape
		#not escaped and not transitioning to escape
		if not temp:
			b = wcwidth(i)
			a += (b>0) and b
		elif i.isalpha(): #is escaped and i is alpha
			escape = False
			continue
		escape = temp
	return a

#fit word to column width
def fitwordtolength(string,length):
	escape = False
	#number of columns passed, number of chars passed
	trace,lentr = 0,0
	for lentr,i in enumerate(string):
		temp = (i == '\x1b') or escape
		#escapes (FSM-style)
		if not temp:
			char = wcwidth(i)
			trace += (char>0) and char
			if trace > length:
				return lentr
		elif i.isalpha(): #is escaped and i is alpha
			escape = False
			continue
		escape = temp
	return lentr + 1

#preserve formatting. this isn't necessary (if you remove the preset colorer)
#but it looks better
def preserveFormatting(line):
	ret = ''
	#only fetch after the last clear
	for i in _EFFECTS:
		if i in line:
			ret += i
	try: #return the last (assumed to be color) ANSI escape used
		return ret + _LAST_COLOR_RE.findall(line)[-1]
	except IndexError: return ret
#breaklines by max column width
def breaklines(string,length):
	string = string.expandtabs(INDENT_LEN)
	THRESHOLD = length/2
	TABSPACE = length - INDENT_LEN

	broken = []
	form = ''
	for i,line in enumerate(string.split("\n")):
		line += " " #ensurance that the last word will capture
		#tab the next lines
		space = (i and TABSPACE) or length
		newline = ((i and INDENT_STR) or "") + form
		while line != "":
			match = WORD_RE.match(line)
			word = match.group(0)
			wordlen = strlen(word)
			newspace = space - wordlen
			#just add the word
			if wordlen < space:
				space = newspace
				newline += word
				line = line[match.end(0):]
			#if there's room for some of the word, and we're not past a threshold
			elif space >= THRESHOLD:
				fitsize = fitwordtolength(word, space)
				line = line[fitsize:]
				newline += word[:fitsize]
			if newspace <= 0:
				broken.append(newline+CLEAR_FORMATTING)
				newline = INDENT_STR+preserveFormatting(newline)
				space = TABSPACE
		if newline != "":
			broken.append(newline+CLEAR_FORMATTING)
			form = preserveFormatting(newline)
	return broken,len(broken)

#------------------------------------------------------------------------------
#DISPLAY/OVERLAY CLASSES

class DisplayException(Exception): pass

def moveCursor(x=0):
	print("\x1b[%d;f"%x,end=CLEAR_FORMATTING)

class schedule:
	def __init__(self):
		self.scheduler = []
		self.taskno = 0
		self.debounce = False
	
	def __call__(self,func,*args):
		if self.debounce:
			self.scheduler.append((func,args))
			return True
		self.bounce(True)
		func(*args)
		self.bounce(False)
	
	def bounce(self,newbounce):
		prev = self.debounce
		if not newbounce:
			self.debounce = True
			while self.taskno < len(self.scheduler):
				task = self.scheduler[self.taskno]
				task[0](*task[1])
				self.taskno+=1
			self.scheduler = []
			self.taskno = 0
		self.debounce = newbounce
		return prev

quitlambda = lambda x: -1
staticize = lambda x: lambda y: x()
staticize2 = lambda x,y: lambda z: x(y)

#overlays
class overlayBase:
	#interface for adding pre-runtime
	#this only needs to be called if you're adding things pre-runtime
	def __init__(self):
		self._altkeys =	 {None:	lambda: -1}
		self._keys =	 {27:	self._callalt}
	def __call__(self,chars):
		try:
			char = _KEY_LUT[chars[0]]
		except: char = chars[0]
		if char in self._keys:	#ignore the command character and trailing -1
			return self._keys[char](chars[1:-1] or [None]) or self._post()
		elif char in range(32,255) and -1 in self._keys:	#ignore the trailing -1
			return self._keys[-1](chars[:-1]) or self._post()
	def _callalt(self,chars):
		return chars[0] in self._altkeys and self._altkeys[chars[0]]()
	def _post(self):
		pass
	def display(self,lines):
		pass
	#nice method to add keys whenever
	def addKeys(self,newFunctions = {}):
		for i,j in newFunctions.items():
			if isinstance(i,str):
				if i.lower().find('a-') == 0:
					i = i[2:]
					if i in _VALID_KEYNAMES[i]:
						i = _VALID_KEYNAMES[i]
					else: raise KeyException('key alt-%s invalid'%i)
				try:
					i = _VALID_KEYNAMES[i]
				except: raise KeyException('key %s not defined'%i)
			self._keys[i] = staticize2(j,self)
	def addResize(self,other):
		self._keys[curses.KEY_RESIZE] = staticize(other.resize)

class listOverlay(overlayBase):
	replace = True
	#worst case column: |(value[0])...(value[1])|
	#		    1    2     345  6	    7
	#worst case rows: |(list member)|(RESERVED)
	#		  1	2	3
	setmins(7,3+RESERVE_LINES)
	def __init__(self,outList,drawOther = None,modes = [""]):
		overlayBase.__init__(self)
		self.it = 0
		self.mode = 0
		self.list = outList
		self._drawOther = drawOther
		self._modes = modes
		self._nummodes = len(modes)
		self._numentries = len(self.list)
		self._keys.update({
			ord('j'):	staticize2(self.increment,1) #V I M
			,ord('k'):	staticize2(self.increment,-1)
			,ord('`'):	quitlambda
			,curses.KEY_DOWN:	staticize2(self.increment,1)
			,curses.KEY_UP:		staticize2(self.increment,-1)
			,curses.KEY_RIGHT:	staticize2(self.chmode,1)
			,curses.KEY_LEFT:	staticize2(self.chmode,-1)
		})
	
	#predefined list iteration methods
	def increment(self,amt):
		if not self._numentries: return
		self.it += amt
		self.it %= self._numentries
	def chmode(self,amt):
		self.mode = (self.mode + amt) % self._nummodes
	
	def display(self,lines):
		lines[0] = BOX_TOP()
		size = DIM_Y-RESERVE_LINES-2
		maxx = DIM_X-2
		#which portion of the lmaxyist is currently displaced
		partition = self.it//size
		listmod = partition*size
		#get the partition of the list we're at, pad the list
		subList = self.list[listmod:listmod+size]
		subList = subList + ["" for i in range(size-len(subList))]
		#display lines
		for i,value in enumerate(subList):
			half = maxx//2
			#add an elipsis in the middle of the string if it can't be displayed; also, right justify
			row = (len(value) > maxx) and value[:max(half-3,1)] + "..." + value[-half:] or value
			row += CLEAR_FORMATTING
			row = row.ljust(BOX_JUST(row))
			if value and self._drawOther is not None:
				rowcol = coloring(row)
				self._drawOther(rowcol,i+listmod)
				row = str(rowcol)
			if i+listmod == self.it:
				row = SELECTED(row)
			else:
				row += CLEAR_FORMATTING

			lines[i+1] = BOX_NOFORM(row)
		#DIM_Y - RESERVE_LINES is the number of lines
		
		if self._nummodes - 1:
			printmode = self._modes[self.mode]
			lines[-1] = CHAR_BOTTOMS[0]+printmode+CHAR_HSPACE*(maxx-len(printmode))+CHAR_BOTTOMS[1]
		else:
			lines[-1] = BOX_BOTTOM()
		return lines

class colorOverlay(overlayBase):
	replace = True
	NAMES = ["Red","Green","Blue"]
	#worst case column: |Red  GreenBlue |
	#		    123456789ABCDEFGH = 17
	#worst case rows: |(color row) (name)(val) (hex)|(RESERVED)
	#		  1	2     3	 4	5 6  7  8
	setmins(17,8+RESERVE_LINES)
	def __init__(self,initcolor = [127,127,127]):
		overlayBase.__init__(self)
		self.color = initcolor
		self._rgb = 0
		self._keys.update({
			ord('`'):		quitlambda
			,ord('k'):		staticize2(self.increment,1)
			,ord('j'):		staticize2(self.increment,-1)
			,curses.KEY_UP:		staticize2(self.increment,1)
			,curses.KEY_DOWN:	staticize2(self.increment,-1)
			,curses.KEY_PPAGE:	staticize2(self.increment,10)
			,curses.KEY_NPAGE:	staticize2(self.increment,-10)
			,curses.KEY_HOME:	staticize2(self.increment,255)
			,curses.KEY_END:	staticize2(self.increment,-255)
			,curses.KEY_LEFT:	staticize2(self.chmode,-1)
			,curses.KEY_RIGHT:	staticize2(self.chmode,1)
		})
	#color manipulation: mode represents color selected
	def increment(self,amt):
		self.color[self._rgb] = max(0,min(255, self.color[self._rgb] + amt))
	def chmode(self,amt):
		self._rgb = (self._rgb + amt) % 3
	def display(self,lines):
		wide = (DIM_X-2)//3 - 1
		space = DIM_Y-RESERVE_LINES-7
		lines[0] = BOX_TOP()
		for i in range(space):
			string = ""
			#draw on this line (ratio of space alotted to line number = ratio of number to 255)
			for j in range(3):
				string += ((space-i)*255 < (self.color[j]*space)) and _COLOR_PAIRS[j+2] or ""
				string += " " * wide + CLEAR_FORMATTING + " "
			#justify (including escape sequence length)
			just = BOX_JUST(string)
			lines[i+1] = BOX_NOFORM(string.rjust(just-1).ljust(just))
		
		lines[-6] = BOX_PART("")
		names,vals = "",""
		for i in range(3):
			names += centered(self.NAMES[i],wide,		i==self._rgb)
			vals += centered(str(self.color[i]),wide,	i==self._rgb)
		lines[-5] = BOX_PART(names) #4 lines
		lines[-4] = BOX_PART(vals) #3 line
		lines[-3] = BOX_PART("") #2 lines
		lines[-2] = BOX_PART(toHexColor(self.color).rjust(int(wide*1.5)+3)) #1 line
		lines[-1] = BOX_BOTTOM() #last line
		return lines

class inputOverlay(overlayBase):
	replace = False
	def __init__(self,prompt,password = False,end=False):
		overlayBase.__init__(self)
		self._done = False
		self._prompt = prompt+': '
		self._password = password
		self._end = end
		roomleft = DIM_X-2-len(self._prompt)
		if roomleft <= 2:
			raise DisplayException("inputOverlay prompt too small")
		self.text = scrollable(roomleft)
		self._keys.update(scrollablecontrol(self.text))
		self._keys.update({
			-1:	self._input
			,10:	staticize(self._finish)
		})
		self._altkeys.update({
			None:	self._stop
			,127:	self.text.delword
		})
	def _input(self,chars):
		self.text.append(bytes(chars).decode())
	#we stopped
	def _finish(self):
		self._done = True
		return -1
	#premature stops, clear beforehand
	def _stop(self):
		if self._end:
			#raising SystemExit is dodgy, since curses.endwin won't get called
			global active
			active = False
		self.text.clear()
		return -1
	def display(self,lines):
		start = DIM_Y//2 - 2
		room = DIM_X-2
		lines[start] = BOX_TOP()
		#make sure we're not too long
		inp = self.text.display()
		#preserve the cursor position save
		if self._password:
			inp = CHAR_CURSOR.join('*'*strlen(i) for i in inp.split(CHAR_CURSOR))
		lines[start+1] = BOX_PART(self._prompt + inp)
		lines[start+2] = BOX_BOTTOM()
	#run in alternate thread to get input
	def waitForInput(self):
		while not self._done:
			time.sleep(.1)
		return str(self.text)

class commandOverlay(inputOverlay):
	replace = False
	def __init__(self,client):
		inputOverlay.__init__(self,'')
		self.parent = client
		self._keys.update({
			10:	staticize(self._run)
			,127:	staticize(self._backspacewrap)
		})
		self._altkeys.update({
			127:	lambda: -1
		})
	def _backspacewrap(self):
		if str(self.text) == '':
			return -1
		self.text.backspace()
	def _run(self):
		text = str(self.text)
		space = text.find(' ')
		command = space == -1 and text or text[:space]
		try:
			command = commands[command]
			add = command(self.parent,text[space+1:].split(' '))
			if isinstance(add,overlayBase):
				self.parent.replaceOverlay(add)
		except: pass
		return -1
	def display(self,lines):
		lines[-1] = CHAR_COMMAND + self.text.display()
		return lines

#overlay for redirecting input after \ is pressed
class escapeOverlay(overlayBase):
	replace = False
	def __init__(self,appendobj):
		overlayBase.__init__(self)
		self._keys.update({
			-1:		lambda x: -1
			,ord('n'):	lambda x: appendobj.append('\n') or -1
			,ord('\\'):	lambda x: appendobj.append('\\') or -1
			,ord('t'):	lambda x: appendobj.append('\t') or -1
		})

#overlay to confirm selection confirm y/n (no slash)
class confirmOverlay(overlayBase):
	replace = False
	def __init__(self,confirmfunc):
		overlayBase.__init__(self)
		self._keys.update({
			ord('y'):	lambda x: confirmfunc() or -1
			,ord('n'):	quitlambda
		})

class mainOverlay(overlayBase):
	replace = True
	addoninit = {}
	#sequence between messages to draw reversed
	_msgSplit = "\x1b" 
	def __init__(self,parent):
		overlayBase.__init__(self)
		self.text = scrollable(DIM_X)
		self.parent = parent
		#these two REALLY need to be private
		self._allMessages = []
		self._lines = []
		#these two too because they select the previous two
		self._selector = 0
		self._filtered = 0
		self._keys.update(scrollablecontrol(self.text))
		self._keys.update({
			-1:			self._input
			,ord('\\'):		staticize(self._replaceback)
			,curses.KEY_F2:		lambda x: self.linklist() or 1
			,curses.KEY_RESIZE:	staticize(self.parent.resize)
		})
		self._altkeys.update({
			ord('k'):		self.selectup	#muh vim t. me
			,ord('j'):		self.selectdown
			,127:			self.text.delword
		})
		self.addKeys(self.addoninit)
	#stop selecting
	def _post(self):
		if self._selector:
			self._selector = 0
			self.parent.display()
	def _replaceback(self):
		self.addOverlay(escapeOverlay(self.text))
	#any other key
	def _input(self,chars):
		if not str(self.text) and len(chars) == 1 and \
		chars[0] == ord(CHAR_COMMAND):
			self.addOverlay(commandOverlay(self.parent))
			return
		#allow unicode input
		self.text.append(bytes(chars).decode())
	#select message down/up
	def selectup(self):
		self._selector += 1
		self._selector = min(self._selector,
			len(self._allMessages)-self._filtered)
		return 1 #don't stop selecting
	def selectdown(self):
		self._selector -= 1
		self._selector = max(self._selector,0)
		#schedule a redraw since we're not highlighting any more
		if not self._selector:
			self.parent.display()
		return 1
	#f2
	def linklist(self):
		#enter key
		def select(me):
			if not len(lastlinks): return
			current = me.list[me.it].split(":")[0] #get the number selected, not the number by iterator
			current = lastlinks[int(current)-1] #this enforces the wanted link is selected
			if not me.mode:
				link_opener(self.parent,current)
			else:
				link_opener(self.parent,current,True)
			#exit
			return -1
		
		#take out the protocol
		dispList = [i.replace("http://","").replace("https://","") for i in reversed(lastlinks)]
		#link number: link, but in reverse
		dispList = ["{}: {}".format(len(lastlinks)-i,j) for i,j in enumerate(dispList)] 

		box = listOverlay(dispList,None,["open","force"])
		box.addKeys({'enter':select})
		self.addOverlay(box)
	#-------------------------FRONTENDS-------------------------
	def addOverlay(self,new):
		self.parent.addOverlay(new)
	#get selector
	def isselecting(self):
		return self._selector
	#frontend for self._allMessages[self._selector] that returns the right one
	def getselect(self,num = None):
		if num is None: num = self._selector
		i,count = 1,1
		while (i <= len(self._allMessages)) and (count <= num):
			j = self._allMessages[-i]
			i += 1
			try:
				if any(k(*j[1]) for k in filters):
					continue
			except: pass
			count += 1
		return self._allMessages[-i+1]
	#does what it says
	def redolines(self):
		newlines = []
		self._filtered = 0
		#get the last terminal line number of messages (worst case)
		for i in self._allMessages[-(DIM_Y-RESERVE_LINES):]:
			try:
				if any(j(*i[1]) for j in filters):
					self._filtered += 1
					continue
			except: pass
			a,b = breaklines(i[0],DIM_X)
			newlines += a
			i[2] = b
			newlines.append(self._msgSplit)
		self._lines = newlines
	#second verse, same as the first
	def clearlines(self):
		self._lines = []
		self._allMessages = []
		self._selector = 0
		self._filtered = 0
		self.parent.resize() #clear the lines the parent makes
	#-------------------------BACKENDS-------------------------
	#add new messages
	def append(self,newline,args = None):
		#undisplayed messages have length zero
		msg = [newline,args,0]
		try:
			if any(i(*args) for i in filters):
				self._allMessages.append(msg)
				self._filtered += 1
				return
		except: pass
		a,b = breaklines(newline,DIM_X)
		self._lines += a
		msg[2] = b
		self._allMessages.append(msg)
		self._lines.append(self._msgSplit)
		self._selector += self._selector>0
	#add lines into lines supplied
	def display(self,lines):
		#seperate traversals
		selftraverse,linetraverse = -1,-2
		lenself, lenlines = len(self._lines),len(lines)
		msgno = 0
		direction = -1 #upward by default
		#we need to go up a certain number of lines if we're drawing from selector
		if self._selector:
			#number of messages up, number of lines traversed up, number of lines visible up
			top,start,visup = 0,0,0
			lenmsg = len(self._allMessages)
			while start < lenmsg and (visup < self._selector or (top-visup+1) < lenlines):
				i = self._allMessages[-start-1]
				start += 1
				try:
					if any(j(*i[1]) for j in filters):
						continue
				except: pass
				visup += 1
				top += i[2]+1 #IMPORTANT FOR THE BREAKING MESSAGE
				#if we've already surpassed self.lines, we need to add to self.lines
				if top > len(self._lines):
					a,b = breaklines(i[0],DIM_X)
					a.append(self._msgSplit)
					self._lines = a + self._lines
					i[2] = b
			#if we draw way past the selected message
			#we're close to the bottom of lines
			if visup > self._selector:
				top = min(top,lenlines+visup-1) #+visup for the breaking lines
			#we start drawing from this line, downward
			selftraverse = -top
			#top-visup+1 just signifies how many drawn lines there are
			linetraverse = -min(lenlines,top-visup+1)
			msgno = visup
			direction = 1
			lenlines = -2 #int <= -2 <=> int < -1)
			lenself = -1 #int <= -1 <=> int < 0
		#this looks horrible, but it's DRY
		while (direction*selftraverse) <= lenself and (direction*linetraverse) <= lenlines:
			if self._lines[selftraverse] == self._msgSplit:
				selftraverse += direction #disregard this line
				msgno -= direction #count lines down downward, up upward
				continue
			reverse = (msgno == self._selector) and _EFFECTS[0]+CHAR_CURSOR or ""
			lines[linetraverse] = reverse + self._lines[selftraverse]
			selftraverse += direction
			linetraverse += direction
		lines[-1] = CHAR_HSPACE*DIM_X
		return lines

#------------------------------------------------------------------------------
#INPUT

#scrollable text input
class scrollable:
	def __init__(self,width):
		self._str = ""
		self._pos = 0
		self._disp = 0
		self.width = width
		self.history = []
		self._selhis = 0
	#return the raw text contained within it
	def __repr__(self):
		return self._str
	#move the cursor and display
	def movepos(self,dist):
		self._pos = max(0,min(len(self._str),self._pos+dist))
		curspos = self._pos - self._disp
		if curspos <= 0: #left hand side
			self._disp = max(0,self._disp+dist)
		elif (curspos+1) >= self.width: #right hand side
			self._disp = min(self._pos-self.width+1,self._disp+dist)
	#display some text
	def display(self):
		text = self._str[:self._pos] + CHAR_CURSOR + self._str[self._pos:]
		text = text.replace("\n",r"\n").replace("\t",r"\t").replace("\r",r"\r")
		text = text[self._disp:self._disp+self.width+len(CHAR_CURSOR)]
		return text[-fitwordtolength(text,self.width):]
	#append new characters and move that length
	def append(self,new):
		self._str = self._str[:self._pos] + new + self._str[self._pos:]
		self.movepos(len(new))
	#backspace
	def backspace(self):
		if not self._pos: return #don't backspace at the beginning of the line
		self._str = self._str[:self._pos-1] + self._str[self._pos:]
		self.movepos(-1)
	#delete char
	def delchar(self):
		self._str = self._str[:self._pos] + self._str[self._pos+1:]
	#delete word
	def delword(self):
		pos = _UP_TO_WORD_RE.match(' '+self._str[:self._pos])
		if pos:
			#we started with a space
			span = pos.span(1)[1] - 1
			#how far we went
			self._str = self._str[:span] + self._str[self._pos:]
			self.movepos(span-self._pos)
		else:
			self._str = self._str[self._pos:]
			self._disp = 0
			self._pos = 0
	#clear the window
	def clear(self):
		self._str = ""
		self._pos = 0
		self._disp = 0
	#home and end functions
	def home(self):
		self._pos = 0
		self._disp = 0
	def end(self):
		self._pos = 0
		self._disp = 0
		self.movepos(len(self._str))
	#history next
	def nexthist(self):
		if self.history:
			self._selhis += (self._selhis < (len(self.history)))
			self._str = self.history[-self._selhis]
			self.end()
	#history prev
	def prevhist(self):
		if self.history:
			self._selhis -= (self._selhis > 0)
			#the next element or an empty string
			self._str = self._selhis and self.history[-self._selhis] or ""
			self.end()
	#add new history entry
	def appendhist(self,new):
		self.history.append(new)
		self.history = self.history[-50:]
		self._selhis = 0

class BotException(Exception): pass

class botclass:
	parent = None
	def setparent(self,overlay):
		if not isinstance(overlay,main):
			raise BotException("botclass.setparent attempted on object other than client.main")
		self.parent = overlay

#main class; handles all IO and defers to overlays
class main:
	_screen = None
	_last = 0
	def __init__(self,chatbot):
		if not isinstance(chatbot,botclass):
			raise BotException("%s not descendent of client.botclass"%\
				type(botclass).__name__)
		self._schedule = schedule()
		self._bottom_edges = [" "," "]

		self.candisplay = 1
		chatbot.setparent(self)
		self.over = mainOverlay(self)
		#input/display stack
		self._ins = [self.over]
	#crux of input
	def input(self):
		try:
			next = -1
			while next == -1:
				next = self._screen.getch()
				time.sleep(.01) #less CPU intensive
			chars = [next]
			while next != -1:
				next = self._screen.getch()
				chars.append(next)
		except KeyboardInterrupt:
			global active
			active = False
			return
		return self._ins[-1](chars)
	#resize the gui
	def resize(self):
		global DIM_X,DIM_Y
		DIM_Y, newx = self._screen.getmaxyx()
		if DIM_Y < _MIN_Y or newx < _MIN_X:
			DIM_X = newx
			self.candisplay = 0
			return
		self.candisplay = 1
		#only redo lines if the width changed
		if DIM_X != newx:
			DIM_X = newx
			self.over.redolines()
			self.over.text.width = newx-1
		self.updateinput()
		self.updateinfo()
		self.display()
	#=------------------------------=
	#|	Loop Frontends		|
	#=------------------------------=
	def loop(self):
		while active:
			if self.input() == -1:
				self._ins.pop()
				if not self._ins: break #insurance
				self.resize()
				
			if len(self._ins)-1 or self.over.isselecting():
				self.display()
			else:
				self.updateinput()
		
	#threaded function that prints the current time every 10 minutes
	#also handles erasing blurbs
	def timeloop(self):
		i = 0
		while active:
			time.sleep(2)
			i+=1
			if time.time() - self._last > 4:
				self.newBlurb()
			#every 600 seconds
			if not i % 300:
				self.msgTime(time.time())
				i=0
	#start the loops and any threads supplied as arguments
	def start(self,screen,*args):
		global active
		active = True
		self._screen = screen
		self._screen.nodelay(1)
		self.resize()
		#for some reason this is too fast; a twentieth of a second isn't very noticeable anyway
		time.sleep(.05) 
		for i in args:
			i.start()
		self.loop()
		active = False

	#=------------------------------=
	#|	Display Backends	|
	#=------------------------------=
	#display backend
	def _display(self):
		if not self.candisplay: return
		lines = ["" for i in range(DIM_Y-RESERVE_LINES)]
		#justify number of lines
		#start with the last "replacing" overlay, then draw all overlays afterward
		start = 1
		while (start < len(self._ins)) and not self._ins[-start].replace:
			start += 1
		for i in self._ins[-start:]:
			i.display(lines)
		#main display method: move to top of screen
		moveCursor()
		curses.curs_set(0)
		#draw each line in lines
		for i in lines:
			print(i,end="\x1b[K\n\r")
		curses.curs_set(1)
		print(CHAR_RETURN_CURSOR,end='')
	#display a blurb
	def _printblurb(self,string):
		if not self.candisplay: return
		moveCursor(DIM_Y-RESERVE_LINES+2)
		if strlen(string) > DIM_X:
			string = string[fitwordtolength(string,DIM_X-3):]+'...'
		print(string+'\x1b[K',end=CHAR_RETURN_CURSOR)
		#for some reason, it won't update input drawing (in IME) until I print something
	#display string in input
	def _updateinput(self):
		if not self.candisplay: return
		string = self.over.text.display()
		moveCursor(DIM_Y-RESERVE_LINES+1)
		print(string+'\x1b[K',end=CHAR_RETURN_CURSOR)
	#display info window
	def _updateinfo(self,right,left):
		if not self.candisplay: return
		moveCursor(DIM_Y)
		self._bottom_edges[0] = left or self._bottom_edges[0]
		self._bottom_edges[1] = right or self._bottom_edges[1]
		room = DIM_X - len(self._bottom_edges[0]) - len(self._bottom_edges[1])
		if room < 1:
			return
		#selected, then turn off
		print("\x1b[7m{}{}{}\x1b[0m".format(self._bottom_edges[0],
			" "*room,self._bottom_edges[1]),end=CHAR_RETURN_CURSOR)

	#=------------------------------=
	#|	Frontends		|
	#=------------------------------=
	def display(self):
		self._schedule(self._display)
	#system message
	def msgSystem(self, base):
		self.over.append(_COLOR_PAIRS[1]+base+CLEAR_FORMATTING)
		self.display()
	#push a system message of the time
	def msgTime(self, numtime = None, predicate=""):
		dtime = time.strftime("%H:%M:%S",time.localtime(numtime or time.time()))
		self.msgSystem(predicate+dtime)
	#parse a message and color it
	def msgPost(self,post,*args):
		parseLinks(post)
		post = coloring(post)
		#run each colorer on the coloring object
		for i in colorers:
			i(post,*args)
		#push the message and move the cursor back to the input window
		self.over.append(str(post),list(args))
		self.display()
	#update input
	def updateinput(self):
		self._schedule(self._updateinput)
	#5 second blurb
	def newBlurb(self,message = ""):
		self._last = time.time()
		self._schedule(self._printblurb,message)
	#update screen bottom
	def updateinfo(self,right = None,left = None):
		self._schedule(self._updateinfo,right,left)

	def addOverlay(self,new):
		if not isinstance(new,overlayBase): return
		new.addResize(self)
		self._ins.append(new)
		#yes, this is still too fast
		time.sleep(.01)
		self.display()
		self.updateinfo() #this looks ugly otherwise
	#replace the top overlay
	def replaceOverlay(self,new):
		self._ins.pop()
		self.addOverlay(new)

	def onerr(self):
		global active
		active = False
		curses.ungetch('\x1b')

#wrapper for adding keys to the main interface
def onkey(keyname):
	def wrapper(func):
		try:
			mainOverlay.addoninit[_VALID_KEYNAMES[keyname]] = func
		except:	raise KeyException("key %s not defined" % keyname)
	return wrapper

#------------------------------------------------------------------------------
#debug stuff
def dbmsg(*args):
	with open("debug","a+") as a:
		for i in args:
			a.write(str(i)+"\t")
		a.write("\n")
		a.close()

#catch error and end client
def catcherr(client,fun,*args):
	def wrap():
		try:
			fun(*args)
		except Exception as e:
			global lasterr
			lasterr = e
			client.onerr()
	return wrap


def start(bot_object,main_function):
	global INDENT_STR
	#why would I modify this at runtime anyway
	INDENT_STR = INDENT_STR[:INDENT_LEN].rjust(INDENT_LEN)
	client = main(bot_object)
	#daemonize functions
	bot_thread = Thread(target=catcherr(client,main_function))
	bot_thread.daemon = True
	printtime = Thread(target=client.timeloop)
	printtime.daemon = True
	#start
	scr = curses.initscr()
	curses.noecho(); curses.cbreak(); scr.keypad(1)
	#okay actually start 
	try:
		client.start(scr, bot_thread, printtime)
	finally:
		curses.echo(); curses.nocbreak(); scr.keypad(0)
		curses.endwin()
	if lasterr:
		raise lasterr
