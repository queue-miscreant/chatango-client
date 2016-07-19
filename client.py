#!/usr/bin/env python3
#TODO: 		make it less of a dance for one overlay to replace another (overlay needs parent to do so) (maybe)
#		make filtered messeges cooperate with selection (add third iterator in "going up loop"
try:
	import curses
except ImportError:
	raise ImportError("ERROR WHILE IMPORTING CURSES, is this running on Windows cmd?")
from os import environ
from threading import Thread
from wcwidth import wcwidth
import sys
import traceback
import re
import time
#check if terminal
if not sys.stdout.isatty():
	raise IOError("This script is not intended to be piped")
#escape has delay typically
environ.setdefault('ESCDELAY', '25')

client = None
active = False
lastlinks = []

WORD_RE = re.compile("[^ ]* ")
ANSI_ESC_RE = re.compile("\x1b"+r"\[[^A-z]*[A-z]")
LINK_RE = re.compile("(https?://.+?\\.[^\n` 　]+)[\n` 　]")
_LAST_COLOR_RE = re.compile("\x1b"+r"\[[^m]*3[^m]*[^m]*m")
INDENT_LEN = 4
INDENT_STR = ""
LAST_INPUT = ""
#guessed terminal dimensions
DIM_X = 40
DIM_Y = 70
RESERVE_LINES = 3
#break if smaller than these
_MIN_X = 0
_MIN_Y = RESERVE_LINES
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
_CLEAR_FORMATTING = '\x1b[m'
#------------------------------------------------------------------------------
#overlay formatting
CHAR_HSPACE = "─"
CHAR_VSPACE = "│"
CHAR_TLCORNER = "┌"
CHAR_TRCORNER = "┐"
CHAR_BLCORNER = "└"
CHAR_BRCORNER = "┘"
CHAR_CURSOR = "|"
CHAR_COMMAND = "`"
#lambdas
_BOX_TOP = lambda: CHAR_TLCORNER + (CHAR_HSPACE * (DIM_X-2)) + CHAR_TRCORNER
#just the number of spaces to justify
_BOX_JUST = lambda x: DIM_X-2+sum([i.end(0)-i.start(0) for i in ANSI_ESC_RE.finditer(x)])
#formatted and sandwiched
_BOX_PART = lambda x: CHAR_VSPACE + x.ljust(_BOX_JUST(x)) + CHAR_VSPACE	
#sandwiched between verticals
_BOX_NOFORM = lambda x: CHAR_VSPACE + x + CHAR_VSPACE
_BOX_BOTTOM = lambda: CHAR_BLCORNER + (CHAR_HSPACE * (DIM_X-2)) + CHAR_BRCORNER
_SELECTED = lambda x: _EFFECTS[0] + x + _CLEAR_FORMATTING
#------------------------------------------------------------------------------
#list of curses keys
#used internally to redirect curses keys
_CURSES_KEYS = {
	9:  'tab',	#htab
	10: 'enter',	#line feed
	13: 'enter',	#carriage return
	27: 'escape',	#escape
	127:'backspace',#delete character
	525:'alt_down', #alt down
	566:'alt_up',	#alt up
}
for i in dir(curses):
	if "KEY" in i:
		_CURSES_KEYS[getattr(curses,i)] = i
_CURSES_KEYS[curses.KEY_ENTER] = 'enter'
_CURSES_KEYS[curses.KEY_BACKSPACE] = 'backspace'
_CURSES_KEYS[curses.KEY_RESIZE] = 'resize'

class KeyException(Exception): pass

def defineKey(value,string):
	if string in _CURSES_KEYS.values(): raise KeyException("Key '{}' already defined".format(string))
	_CURSES_KEYS[value] = string

def cloneKey(fro,to):
	if fro not in _CURSES_KEYS.values(): raise KeyException("Key '{}' not defined")
	_CURSES_KEYS[to] = _CURSES_KEYS[fro]

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
#	__init__ is like a static __call__
	def __init__(self,client,link,forcelink=False):
		#extension
		ext = link[link.rfind(".")+1:].lower()
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
			getattr(self, 'default')(client,link)
	#raise exception if not overloaded
	def default(*args):
		raise Exception("No regular link handler defined")

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
		def ret():
			new = commandOverlay(cli)
			new.inpstr = self.list[self.it]
			cli.replaceOverlay(new)
		return ret
	commandsList = listOverlay(list(commands))
	commandsList.addKeys({
		'enter':select(commandsList)
	})
	cli.addOverlay(commandsList)
	
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
		return coloring(self._str[sliced])
	def __add__(self,other):
		return coloring(self._str + other)
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
	#prebuilts
	def prepend(self,new):
		self._str = new + self._str
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
	msg += _CLEAR_FORMATTING

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

#fit word to byte length
def fitwordtolength(string,length):
	escape = False
	#number of columns passed, number of chars passed
	trace,lentr = 0,0
	for lentr,i in enumerate(string):
		temp = (i == '\x1b') or escape
		#print(lentr,i,temp,escape)
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

#preserve formatting. this isn't necessary (if you remove the preset colorer), but it looks better
def preserveFormatting(line):
	ret = ''
	#only fetch after the last clear
	lastClear = line.rfind(_CLEAR_FORMATTING)
	if lastClear+1: line = line[:lastClear]
	for i in _EFFECTS:
		if i in line:
			ret += i
	try: #return the last (assumed to be color) ANSI escape used
		return ret + _LAST_COLOR_RE.findall(line)[-1]
	except IndexError: return ret

def breaklines(string, length = 0):
	#if this is in the function args, it can't be changed later
	if not length:
		length = DIM_X
	tab = INDENT_STR[:INDENT_LEN].rjust(INDENT_LEN)
	THRESHOLD = length/2
	TABSPACE = length - len(tab)

	broken = []
	form = ''
	for i,line in enumerate(string.split("\n")):
		line += " " #ensurance that the last word will capture
		#tab the next lines
		space = (i and TABSPACE) or length
		newline = ((i and tab) or "") + form
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
				broken.append(newline+_CLEAR_FORMATTING)
				newline = tab+preserveFormatting(newline)
				space = TABSPACE
		if newline != "":
			broken.append(newline+_CLEAR_FORMATTING)
			form = preserveFormatting(newline)
	return broken,len(broken)

#------------------------------------------------------------------------------
#DISPLAY/OVERLAY CLASSES

class DisplayException(Exception): pass

def moveCursor(x=0):
	print("\x1b[%d;f"%x,end=_CLEAR_FORMATTING)

def printLine(x):
	print(x,end="\x1b[K\n\r")

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

#overlays
class overlayBase:
	def onescape(self):
		return -1
	def display(self):
		raise DisplayException("Overlay without corresponding display")
	#nice method to add keys whenever
	def addKeys(self,newFunctions = {}):
		for i,j in newFunctions.items():
			if type(i) == str:
				setattr(self,"on"+i,j)
			else:
				setattr(self,"on"+_CURSES_KEYS[i],j)
	def addResize(self,other):
		setattr(self,"onresize",other.resize)

#yes, this is this simple
class confirmOverlay(overlayBase):
	replace = False
	def __init__(self,confirmfunc):
		self.confirm = confirmfunc
	def display(self,lines):
		return lines
	def oninput(self,chars):
		cmd = chr(chars[0]).lower()
		if cmd == 'y':
			self.confirm()
		elif cmd == 'n':
			return -1

class listOverlay(overlayBase):
	replace = True
	#worst case column: |(value[0])...(value[1])|
	#		    1    2     345  6	    7
	#worst case rows: |(list member)|(RESERVED)
	#		  1	2	3
	setmins(7,3+RESERVE_LINES)
	def __init__(self,outList,drawOther = None,modes = [""]):
		self.it = 0
		self.mode = 0
		self.list = outList
		if drawOther:
			setattr(self,"drawOther",drawOther)
		self.modes = modes
		self.nummodes = len(modes)
	
	def oninput(self,text):
		command = chr(text[0])
		#V I M
		#I
		#M
		if command == 'j': #down
			self.onKEY_DOWN()
		elif command == 'k': #up
			self.onKEY_UP()
		elif command == '`':
			return -1
	
	def display(self,lines):
		lines[0] = _BOX_TOP()
		size = DIM_Y-RESERVE_LINES-2
		maxx = DIM_X-2
		#which portion of the lmaxyist is currently displaced
		partition = self.it//size
		#get the partition of the list we're at, pad the list
		subList = self.list[size*partition:size*(partition+1)]
		subList = subList + ["" for i in range(size-len(subList))]
		#display lines
		i = 0
		for i,value in enumerate(subList):
			half = maxx//2
			#add an elipsis in the middle of the string if it can't be displayed; also, right justify
			row = (len(value) > maxx) and value[:max(half-3,1)] + "..." + value[-half:] or value
			row += _CLEAR_FORMATTING
			row = row.ljust(_BOX_JUST(row))
			if value and hasattr(self,'drawOther'):
				row = str(self.drawOther(coloring(row),i))

			if i+size*partition == self.it:
				row = _SELECTED(row)
			else:
				row += _CLEAR_FORMATTING

			lines[i+1] = _BOX_NOFORM(row)
		#DIM_Y - RESERVE_LINES is the number of lines
		
		if self.nummodes - 1:
			printmode = self.modes[self.mode]
			lines[-1] = CHAR_BLCORNER+printmode+CHAR_HSPACE*(maxx-len(printmode))+CHAR_BRCORNER
		else:
			lines[-1] = _BOX_BOTTOM()
		return lines
	#predefined list iteration methods
	def onKEY_UP(self):
		if not len(self.list): return
		self.it -= 1
		self.it %= len(self.list)
	def onKEY_DOWN(self):
		if not len(self.list): return
		self.it += 1
		self.it %= len(self.list)
	def onKEY_RIGHT(self):
		self.mode = (self.mode + 1) % self.nummodes
	def onKEY_LEFT(self):
		self.mode = (self.mode - 1) % self.nummodes

class colorOverlay(overlayBase):
	replace = True
	names = ["Red","Green","Blue"]
	#worst case column: |Red  GreenBlue |
	#		    123456789ABCDEFGH = 17
	#worst case rows: |(color row) (name)(val) (hex)|(RESERVED)
	#		  1	2     3	 4	5 6  7  8
	setmins(17,8+RESERVE_LINES)
	def __init__(self,initcolor = [127,127,127]):
		self.color = initcolor
		self.mode = 0
	#draw replacement
	def display(self,lines):
		wide = (DIM_X-2)//3 - 1
		space = DIM_Y-RESERVE_LINES-7
		if wide < 4 or space < 5:
			raise DisplayException("Terminal size too small")
		
		def centered(x,y):
			pre = x.rjust((wide+len(x))//2).ljust(wide)
			if y==self.mode: pre = _SELECTED(pre)
			return pre
		lines[0] = _BOX_TOP()
		for i in range(space):
			string = ""
			#draw on this line (ratio of space alotted to line number = ratio of number to 255)
			for j in range(3):
				string += ((space-i)*255 < (self.color[j]*space)) and _COLOR_PAIRS[j+2] or ""
				string += " " * wide + _CLEAR_FORMATTING + " "
			#justify (including escape sequence length)
			just = _BOX_JUST(string)
			lines[i+1] = _BOX_NOFORM(string.rjust(just-1).ljust(just))
		
		lines[-6] = _BOX_PART("")
		names = "{}{}{}".format(*[centered(j,i) for i,j in enumerate(self.names)])
		vals = "{}{}{}".format(*[centered(str(j),i) for i,j in enumerate(self.color)])
		lines[-5] = _BOX_PART(names) #4 lines
		lines[-4] = _BOX_PART(vals) #3 line
		lines[-3] = _BOX_PART("") #2 lines
		lines[-2] = _BOX_PART(toHexColor(self.color).rjust(int(wide*1.5)+3)) #1 line
		lines[-1] = _BOX_BOTTOM() #last line
		return lines
	#color manipulation: mode represents color selected
	def onKEY_UP(self):
		self.color[self.mode] += 1
		if self.color[self.mode] > 255:
			self.color[self.mode] = 255
	def onKEY_DOWN(self):
		self.color[self.mode] -= 1
		if self.color[self.mode] < 0:
			self.color[self.mode] = 0
	#pageup
	def onKEY_PPAGE(self):
		self.color[self.mode] += 10
		if self.color[self.mode] > 255:
			self.color[self.mode] = 255
	#pagedown
	def onKEY_NPAGE(self):
		self.color[self.mode] -= 10
		if self.color[self.mode] < 0:
			self.color[self.mode] = 0
	def onKEY_HOME(self):
		self.color[self.mode] = 255
	def onKEY_END(self):
		 self.color[self.mode] = 0
	def onKEY_RIGHT(self):
		self.mode = (self.mode + 1) % 3
	def onKEY_LEFT(self):
		self.mode = (self.mode - 1) % 3

class inputOverlay(overlayBase):
	replace = False
	def __init__(self,prompt,password = False,end=False):
		self.inpstr = ''
		self.done = False
		self.prompt = prompt+': '
		self.password = password
		self.end = end
	def display(self,lines):
		start = DIM_Y//2 - 2
		room = DIM_X-2
		lines[start] = _BOX_TOP()
		out = self.prompt
		#make sure we're not too long
		lenout = len(out)
		if lenout > room-2:
			raise DisplayException("Terminal size too small")
		inp = self.password and '*'*len(self.inpstr) or self.inpstr
		out += inp[(len(inp)+lenout > room) and (len(inp)-room+lenout):]
		lines[start+1] = _BOX_PART(out)
		lines[start+2] = _BOX_BOTTOM()
		return lines
	def oninput(self,chars):
		self.inpstr += bytes(chars).decode()
	def onbackspace(self):
		self.inpstr = self.inpstr[:-1]
	def onenter(self):
		self.done = True
		return -1
	def onescape(self):
		if self.end:
			#raising SystemExit is dodgy, since curses.endwin won't get called
			global active
			active = False
		self.inpstr = ''
		return -1
	#run in alternate thread to get input
	def waitForInput(self):
		while not self.done:
			time.sleep(.1)
		return self.inpstr

class commandOverlay(inputOverlay):
	replace = False
	def __init__(self,client):
		inputOverlay.__init__(self,'')
		self.parent = client
	def display(self,lines):
		final = lines[-1]
		content = CHAR_COMMAND + self.inpstr
		lines[-1] = content + final[len(content):]
		return lines
	def onbackspace(self):
		if not self.inpstr:
			return -1
		self.inpstr = self.inpstr[:-1]
	def onalt_backspace(self):
		return -1
	def onenter(self):
		#when this function is delegated, it's at the top of the ins stack; I can't return -1 
		#without the function terminating early, and it's too late at the end if a command opens an overlay
		#pop from the top now
		self.parent.ins.pop()
		self.parent.display()
		text = self.inpstr
		space = text.find(' ')
		command = space == -1 and text or text[:space]
		try:
			command = commands[command]
			command(self.parent,text[space+1:].split(' '))
		except Exception as esc: dbmsg(esc)

class mainOverlay(overlayBase):
	replace = True
	#sequence between messages to draw reversed
	msgSplit = "\x1b" 
	def __init__(self,parent):
		self.text = scrollable(DIM_X)
		self.allMessages = []
		self.lines = []
		self.selector = 0
		self.filtered = 0
		self.parent = parent
	#backspace
	def onbackspace(self):
		self.text.backspace()
		self.stopselect()
	def onKEY_DC(self):
		self.text.delback()
		self.stopselect()
	#any other key
	def oninput(self,chars):
		if not str(self.text) and len(chars) == 1 and chars[0] == ord(CHAR_COMMAND):
			self.addOverlay(commandOverlay(self.parent))
			return
		#allow unicode input
		self.text.append(bytes(chars).decode())
		self.stopselect()
	#home
	def onKEY_SHOME(self):
		self.text.clear()
		self.stopselect()
	#arrow keys
	def onKEY_LEFT(self):
		self.text.movepos(-1)
		self.stopselect()
	def onKEY_RIGHT(self):
		self.text.movepos(1)
		self.stopselect()
	def onKEY_UP(self):
		self.text.nexthist()
	def onalt_up(self):
		self.selector += 1
		self.selector = min(self.selector,len(self.allMessages)-self.filtered)
	def onalt_k(self):
		self.onalt_up()
	def onKEY_DOWN(self):
		self.text.prevhist()
	def onalt_down(self):
		self.selector -= 1
		self.selector = max(self.selector,0)
		#schedule a redraw since we're not highlighting any more
		if not self.selector:
			self.parent.display()
	def onalt_j(self):
		self.onalt_down()
	def onKEY_HOME(self):
		self.text.home()
		self.stopselect()
	def onKEY_END(self):
		self.text.end()
		self.stopselect()
	#shifted delete = backspace word
	def onalt_backspace(self):
		self.text.delword()
		self.stopselect()
	#f2
	def onKEY_F2(self):
		#special wrapper to inject functionality for newlines in the list
		def select(me):
			def ret():
				if not len(lastlinks): return
				current = me.list[me.it].split(":")[0] #get the number selected, not the number by iterator
				current = lastlinks[int(current)-1] #this enforces the wanted link is selected
				if not me.mode:
					link_opener(self.parent,current)
				else:
					link_opener(self.parent,current,True)
				#exit
				return -1
			return ret
		
		#take out the protocol
		dispList = [i.replace("http://","").replace("https://","") for i in reversed(lastlinks)]
		#link number: link, but in reverse
		dispList = ["{}: {}".format(len(lastlinks)-i,j) for i,j in enumerate(dispList)] 
	
		box = listOverlay(dispList,None,["open","force"])
		box.addKeys({
			'enter':select(box),
		})
		self.addOverlay(box)
	#resize
	def onresize(self):
		self.parent.resize()

	def stopselect(self):
		if self.selector:
			self.selector = 0
			self.parent.display()
	#add new messages
	def append(self,newline,args = None):
		#undisplayed messages have length zero
		msg = [newline,args,0]
		try:
			if any(i(*args) for i in filters):
				self.allMessages.append(msg)
				self.filtered += 1
				return
		except: pass
		a,b = breaklines(newline)
		self.lines += a
		msg[2] = b
		self.allMessages.append(msg)
		self.lines.append(self.msgSplit)
		self.selector += self.cangoup()

	def msgup(self,num = None):
		if num is None: num = self.selector
		i,count = 1,1
		while (i <= len(self.allMessages)) and (count <= num):
			j = self.allMessages[-i]
			i += 1
			try:
				if any(k(*j[1]) for k in filters):
					continue
			except: pass
			count += 1
		return self.allMessages[-i+1]
	
	def cangoup(self):
		return self.selector>0 and (self.selector+self.filtered > len(self.allMessages))

	#does what it says
	def redolines(self):
		newlines = []
		self.filtered = 0
		#get the last terminal line number of messages (worst case)
		for i in self.allMessages[-(DIM_Y-RESERVE_LINES):]:
			try:
				if any(j(*i[1]) for j in filters):
					self.filtered += 1
					continue
			except: pass
			a,b = breaklines(i[0])
			newlines += a
			i[2] = b
			newlines.append(self.msgSplit)
		self.lines = newlines

	#add lines into lines supplied
	def display(self,lines):
		#seperate traversals
		selftraverse,linetraverse = -1,-2
		lenself, lenlines = len(self.lines),len(lines)
		msgno = 0
		direction = -1 #upward by default
		#we need to go up a certain number of lines if we're drawing from selector
		if self.selector:
			#number of messages up, number of lines traversed up, number of lines visible up
			top,start,visup = 0,0,0
			lenmsg = len(self.allMessages)
			while start < lenmsg and (start < self.selector or (top-visup+1) < lenlines):
				i = self.allMessages[-start-1]
				start += 1
				try:
					if any(j(*i[1]) for j in filters):
						continue
				except: pass
				visup += 1
				top += i[2]+1 #IMPORTANT FOR THE BREAKING MESSAGE
				#if we've already surpassed self.lines, we need to add to self.lines
				if top > len(self.lines):
					a,b = breaklines(i[0])
					a.append(self.msgSplit)
					self.lines = a + self.lines
					i[2] = b
			#adjust if we went too far up
			if visup > self.selector:
				top = min(top,top+lenlines-(top-visup+1))
			temp = top-start-visup+1
			if temp < 0:
				lenlines += temp
			#we start drawing from this line, downward
			dbmsg()
			selftraverse = -top
			linetraverse = -lenlines
			msgno = visup
			direction = 1
			#legacy loop statement was this
			#while (selftraverse < 0) and linetraverse < -1:
			lenlines = -2 #int <= -2 <=> int < -1)
			lenself = -1 #int <= -1 <=> int < 0
		#this looks horrible, but it's DRY
		while (direction*selftraverse) <= lenself and (direction*linetraverse) <= lenlines:
			if self.lines[selftraverse] == self.msgSplit:
				selftraverse += direction #disregard this line
				msgno -= direction #count lines down downward, up upward
				continue
			reverse = (msgno == self.selector) and _EFFECTS[0] or ""
			lines[linetraverse] = reverse + self.lines[selftraverse]
			selftraverse += direction
			linetraverse += direction
		lines[-1] = CHAR_HSPACE*DIM_X
		return lines
	def stats(self):
		return repr(self.allMessages[-self.selector][0])
	#window frontend
	def addOverlay(self,new):
		self.parent.addOverlay(new)

#------------------------------------------------------------------------------
#INPUT

#scrollable text input
class scrollable:
	def __init__(self,width):
		self._text = ""
		self.pos = 0
		self.disp = 0
		self.history = []
		self.selhis = 0
		self.width = width
	#return the raw text contained within it
	def __repr__(self):
		return self._text
	#append new characters and move that length
	def append(self,new):
		self._text = self._text[:self.pos] + new + self._text[self.pos:]
		self.movepos(len(new))
	#backspace
	def backspace(self):
		if not self.pos: return #don't backspace at the beginning of the line
		self._text = self._text[:self.pos-1] + self._text[self.pos:]
		self.movepos(-1)
	#delete char back
	def delback(self):
		self._text = self._text[:self.pos] + self._text[self.pos+1:]
	#delete word
	def delword(self):
		pos = (' '+self._text[:self.pos]).rfind(' ')
		if not pos+1: return
		if not pos:
			self._text = self._text[self.pos:]
			self.disp = 0
			self.pos = 0
			return
		self._text = self._text[:pos-1] + self._text[self.pos:]
		#move back the word length
		self.movepos(pos-self.pos-1)
	#clear the window
	def clear(self):
		self._text = ""
		self.pos = 0
		self.disp = 0
	#home and end functions
	def home(self):
		self.pos = 0
		self.disp = 0
	def end(self):
		self.home()
		self.movepos(len(self._text))
	#move the cursor and display
	def movepos(self,dist):
		self.pos = max(0,min(len(self._text),self.pos+dist))
		#if we're at the end, but not the beginning OR we're past the width, move the cursor
		if (self.pos == self.disp and self.pos != 0) or (self.pos-self.disp+1) >= self.width:
			self.disp = max(0,min(self.pos-self.width+1,self.disp+dist))
	#display some text
	def display(self):
		text = self._text[:self.pos] + CHAR_CURSOR + self._text[self.pos:]
		text = text.replace("\n",r"\n").replace("\t",r"\t").replace("\r",r"\r")
		text = text[self.disp:self.disp+self.width]
		#-1 to compensate for the cursor
		return text[-fitwordtolength(text[::-1],self.width)-1:]
	#history next
	def nexthist(self):
		if len(self.history) > 0:
			self.selhis += (self.selhis < (len(self.history)))
			self._text = self.history[-self.selhis]
			self.disp = 0
			self.movepos(len(self._text))
	#history prev
	def prevhist(self):
		if len(self.history) > 0:
			self.selhis -= (self.selhis > 0)
			#the next element or an empty string
			self._text = self.selhis and self.history[-self.selhis] or ""
			self.disp = 0
			self.movepos(len(self._text))
	#add new history entry
	def appendhist(self,new):
		self.history.append(new)
		self.history = self.history[-50:]
		self.selhis = 0

class BotException(Exception): pass

class botclass:
	parent = None
	def setparent(self,overlay):
		if not isinstance(overlay,main):
			raise BotException("Attempted to set bot parent to instance other than client.main")
		self.parent = overlay

#main class; handles all IO and defers to overlays
class main:
	screen = None
	last = 0
	def __init__(self,chatbot):
		if not isinstance(chatbot,botclass):
			raise BotException("Bot instance not descendent of client.botclass")
		#artifacts from client.display
		self.schedule = schedule()
		self.bottom_edges = [" "," "]

		chatbot.setparent(self)
		self.over = mainOverlay(self)
		#input/display stack
		self.ins = [self.over]
	#crux of input
	def input(self):
		try:
			chars = [self.screen.getch()]
		except KeyboardInterrupt:
			global active
			active = False
			return
		#get as many chars as possible
		self.screen.nodelay(1)
		next = 0
		while next+1:
			next = self.screen.getch()
			chars.append(next)
		self.screen.nodelay(0)
		keyAction = ""
		#alt keys are of the form 27, (key sequence)
		if len(chars) > 2 and chars[0] == 27:
			chars.pop(0)
			keyAction = 'alt_'
			keyAction += _CURSES_KEYS.get(chars[0]) or chr(chars[0])
		else:
			keyAction += _CURSES_KEYS.get(chars[0]) or ""
		#delegate to display stack
		self = self.ins[-1]
		#run onKEY function
		if keyAction and hasattr(self,"on"+keyAction):
			return getattr(self,"on"+keyAction)()
		#otherwise, just grab input characters
		if not keyAction and chars[0] in range(32,255) and hasattr(self,"oninput"):
			return getattr(self,"oninput")(chars[:-1])
	#resize the gui
	def resize(self):
		global DIM_X,DIM_Y
		DIM_Y, newx = self.screen.getmaxyx()
		if DIM_Y < _MIN_Y or newx < _MIN_X:
			raise DisplayException("Terminal size too small")
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
				self.ins.pop()
				if not self.ins: break #insurance
				self.resize()
				
			if len(self.ins)-1 or self.over.selector:
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
			if time.time() - self.last > 4:
				self.newBlurb()
			#every 600 seconds
			if not i % 300:
				self.msgTime(time.time())
				i=0
	#start the loops and any threads supplied as arguments
	def start(self,screen,*args):
		global active
		active = True
		self.screen = screen
		self.resize()
		curses.curs_set(0)
		for i in args:
			i.start()
		self.loop()
		active = False

	#=------------------------------=
	#|	Display Backends	|
	#=------------------------------=
	#display backend
	def _display(self):
		size = DIM_Y-RESERVE_LINES
		#justify number of lines
		lines = ["" for i in range(size)]
		#start with the last "replacing" overlay, then draw all overlays afterward
		start = 1
		while (start < len(lines)) and not self.ins[-start].replace:
			start += 1
		for i in self.ins[-start:]:
			lines = i.display(lines)
		#main display method: move to top of screen
		moveCursor()
		#draw each line in lines
		for i in lines:
			printLine(i)
	#display a blurb
	def _printblurb(self,string):
		moveCursor(DIM_Y-RESERVE_LINES+2)
		if strlen(string) > DIM_X:
			string = string[fitwordtolength(string,DIM_X-3):]+'...'
		printLine(string)
		moveCursor(DIM_Y-RESERVE_LINES)
		#for some reason, it won't update input drawing (in IME) until I print something
		print('')
	#display string in input
	def _updateinput(self):
		string = self.over.text.display()
		moveCursor(DIM_Y-RESERVE_LINES+1)
		printLine(string)
		moveCursor(DIM_Y-RESERVE_LINES)
		print('')
	#display info window
	def _updateinfo(self,right,left):
		moveCursor(DIM_Y)
		self.bottom_edges[0] = left or self.bottom_edges[0]
		self.bottom_edges[1] = right or self.bottom_edges[1]
		room = DIM_X - len(self.bottom_edges[0]) - len(self.bottom_edges[1])
		if room < 1:
			raise DisplayException("Terminal size too small")
		#selected, then turn off
		print("\x1b[7m{}{}{}\x1b[0m".format(self.bottom_edges[0]," "*room,self.bottom_edges[1]),end="")
		moveCursor(DIM_Y-RESERVE_LINES)
		print('')

	#=------------------------------=
	#|	Frontends		|
	#=------------------------------=
	def display(self):
		self.schedule(self._display)
	#system message
	def msgSystem(self, base):
		self.over.append(_COLOR_PAIRS[1]+base+_CLEAR_FORMATTING)
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
		self.schedule(self._updateinput)
	#5 second blurb
	def newBlurb(self,message = ""):
		self.last = time.time()
		self.schedule(self._printblurb,message)
	#update screen bottom
	def updateinfo(self,right = None,left = None):
		self.schedule(self._updateinfo,right,left)

	def addOverlay(self,new):
		new.addResize(self)
		self.ins.append(new)
		#for some reason this is too fast; a hundredth of a second isn't very noticeable anyway
		time.sleep(.01)
		self.display()
		self.updateinfo() #this looks ugly otherwise
	#replace the top overlay
	def replaceOverlay(self,new):
		self.ins.pop()
		self.addOverlay(new)

	def onerr(self):
		global active
		active = False
		self.msgSystem("An error occurred. Press any button to exit...")

#wrapper for adding keys to the main interface
def onkey(keyname):
	def wrapper(func):
		if type(keyname) == str:
			setattr(mainOverlay,"on"+keyname,func)
		else:
			setattr(mainOverlay,"on"+_CURSES_KEYS[keyname],func)
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
			dbmsg(''.join(traceback.format_exception(*sys.exc_info())))
			client.onerr()
	return wrap


def start(bot_object,main_function):
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
