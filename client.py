from os import environ
import re
import time
import curses

environ.setdefault('ESCDELAY', '25')

WORD_RE = re.compile("[^ ]* ")
ANSI_ESC_RE = re.compile("\x1b"+r"\[[^A-z]*[A-z]")
INDENT_LEN = 4
INDENT_STR = ""
#guessed terminal dimensions
DIM_X = 40
DIM_Y = 70
RESERVE_LINES = 3

#------------------------------------------------------------------------------
#valid colors to add
COLORS = ['black','red','green','yellow','blue','magenta','cyan','white','','none']
#0 = reverse; 1 = underline
_EFFECTS = ['\x1b[7m','\x1b[4m']
#		Normal/Normal	Red/White	Red		Green		Blue
_COLOR_PAIRS = ['\x1b[39;49m','\x1b[31;47m','\x1b[31;41m','\x1b[32;42m','\x1b[34;44m']
_CLEAR_FORMATTING = '\x1b[m'
_NUM_PREDEFINED = len(_COLOR_PAIRS)

_SELECTED = lambda x: _EFFECTS[0] + x + _CLEAR_FORMATTING
_MOVE_CURSOR = lambda x: print("\x1b[%d;f"%x,end=_CLEAR_FORMATTING)
_DELETE_REST_OF_LINE = lambda x: print(x,end="\x1b[K\n\r")

#------------------------------------------------------------------------------
#overlay formatting
CHAR_HSPACE = "─"
CHAR_VSPACE = "│"
CHAR_TLCORNER = "┌"
CHAR_TRCORNER = "┐"
CHAR_BLCORNER = "└"
CHAR_BRCORNER = "┘"
CHAR_CURSOR = "|"

_BOX_TOP = lambda: CHAR_TLCORNER + (CHAR_HSPACE * (DIM_X-2)) + CHAR_TRCORNER
_BOX_JUST = lambda x: DIM_X-2+sum([i.end(0)-i.start(0) for i in ANSI_ESC_RE.finditer(x)])
_BOX_PART = lambda x: CHAR_VSPACE + x.ljust(_BOX_JUST(x)) + CHAR_VSPACE
_BOX_NOFORM = lambda x: CHAR_VSPACE + x + CHAR_VSPACE
_BOX_BOTTOM = lambda: CHAR_BLCORNER + (CHAR_HSPACE * (DIM_X-2)) + CHAR_BRCORNER

#------------------------------------------------------------------------------
#list of curses keys
#used internally to redirect curses keys
_CURSES_KEYS = {
	9:  'tab',	#htab
	10: 'enter',	#line feed
	13: 'enter',	#carriage return
	27: 'escape',	#escape
	127:'backspace',#delete character
}
for i in dir(curses):
	if "KEY" in i:
		_CURSES_KEYS[getattr(curses,i)] = i
_CURSES_KEYS[curses.KEY_ENTER] = 'enter'
_CURSES_KEYS[curses.KEY_BACKSPACE] = 'backspace'
_CURSES_KEYS[curses.KEY_RESIZE] = 'resize'


#conversions to and from hex strings ([255,255,255] <-> FFFFFF)
toHexColor = lambda rgb: ''.join([hex(i)[2:].rjust(2,'0') for i in rgb])
fromHexColor = lambda hexStr: [int(hexStr[2*i:2*i+2],16) for i in range(3)]

colorers = []
commands = {}
filters = []

#debug stuff
def dbmsg(*args):
	with open("debug","a+") as a:
		for i in args:
			a.write(str(i)+"\t")
		a.write("\n")
		a.close()

class link_opener:
#	__init__ is like a static __call__
	def __init__(self,client,link):
		#extension
		ext = link[link.rfind(".")+1:].lower()
		try:
			if len(ext) <= 4 and hasattr(self,ext):
				getattr(self, ext)(client,link,ext)
			else:
				getattr(self, 'htmllink')(client,link)
		except AttributeError as exc:
			pass

class ColoringException(Exception):
	pass

class DisplayException(Exception):
	pass

class coloring:
	default = None
	def __init__(self,string):
		self.str = string
	
	def __call__(self):
		return self.str

	#insert color at position p with color c
	def insertColor(self,p,c=-1,add = True):
		c = self.default if c == -1 else c
		try:
			c = type(c) != str and _COLOR_PAIRS[c + (add and _NUM_PREDEFINED)] or c 
		except IndexError:
			raise ColoringException("Foreground/Background pair not defined")
		self.str = self.str[:p] + c + self.str[p:]
		#return length of c to adjust trackers
		return len(c)
	
	def prepend(self,new):
		self.str = new + self.str
	
	def append(self,new):
		self.str = self.str + new 

	#add effect to string (if test is true)
	def addEffect(self, number, test = True):
		self.str = (test and _EFFECTS[number] or "") + self.str
	
	def ljust(self,spacing):
		self.str = self.str.ljust(spacing)
	
	@staticmethod
	def definepair(fore, bold = None, back = 'none'):
		global _COLOR_PAIRS
		pair = '\x1b[3%d' % COLORS.index(fore);
		pair += bold and ";1" or ";22"
		pair += ';4%d' % COLORS.index(back) or ""
		_COLOR_PAIRS.append(pair+'m')

#add links to a list
def parseLinks(raw,lastlinks):
	#in case the raw message ends wzith a link
	newLinks = []
	#look for whole word links starting with http:// or https://
	newLinks = [i for i in re.findall("(https?://.+?\\.[^ \n]+)[\n ]",raw+" ")]
	#don't add the same link twice
	for i in newLinks:
		while newLinks.count(i) > 1:
			newLinks.remove(i)
	#lists are passed by reference
	lastlinks += newLinks

#byte length of string (sans escape sequences)
def strlen(string):
	init = len(bytes(string,'utf-8'))
	for i in ANSI_ESC_RE.finditer(string):
		init += i.start(0) - i.end(0)
	return init

#fit word to byte length
def fitwordtolength(string,length):
	add = True
	#byte count
	trace = 0
	for lentr,i in enumerate(string):
		char = len(bytes(i,"utf-8"))
		#escapes (FSM-style)
		if add:
			add = i != '\x1b'
			trace += char
			if trace > length:
				break
			continue
		add = i.isalpha()
		if add and ((trace+char) > length):
			break
	return lentr
		

def breaklines(string, length = 0, tab = None):
	#if this is in the function args, it can't be changed later
	if not length:
		length = DIM_X
	if tab is None:
		tab = INDENT_STR[:INDENT_LEN].rjust(INDENT_LEN)
	THRESHOLD = length/2
	TABSPACE = length - len(tab)

	broken = []
	for i,line in enumerate(string.split("\n")):
		line += " " #ensurance that the last word will capture
		#tab the next lines
		space = (i and TABSPACE) or length
		newline = (i and tab) or ""
		while line != "":
			match = WORD_RE.match(line)
			word = match.group(0)
			wordlen = strlen(word)
			newspace = space - wordlen
			if wordlen < space:
				space = newspace
				newline += word
				line = line[match.end(0):]
			#if there's room for some of the word, and we're not past a threshold
			elif space >= THRESHOLD:
				fitsize = fitwordtolength(word, space)
				line = line[fitsize-1:]
				newline += word[:fitsize]
			
			if newspace <= 0:
				broken.append(newline)
				newline = tab
				space = TABSPACE
		if newline != "":
			broken.append(newline)
	return broken

class display:
	allMessages = []
	lines = []
	bottom_edges = [" "," "]
	overlay = None

	def __init__(self):
		pass
	
	def redoLines(self):
		newlines = []
		#get the last terminal line number of messages (worst case)
		for i in self.allMessages[-(DIM_Y-RESERVE_LINES):]:
			try:
				if any(j(*i[1]) for j in filters):
					continue
			except: pass
			newlines += breaklines(i[0])
		self.lines = newlines
	
	def display(self):
		#if this is a replacement overlay, display that instead
		if self.overlay and self.overlay.replace:
			self.overlay.display()
			return
		_MOVE_CURSOR(0)
		size = DIM_Y-RESERVE_LINES-1
		#draw each line in lines
		i = 0
		for i,j in enumerate(self.lines[-size:]):
			_DELETE_REST_OF_LINE(j)
		
		for k in range(size - i - 1):
			_DELETE_REST_OF_LINE("")
		
		#draw the overlay
		if self.overlay:
			self.overlay.display()
		#fancy line
		_DELETE_REST_OF_LINE(CHAR_HSPACE*DIM_X)
	
	def append(self,newline,args = None):
		self.allMessages.append((newline,args))
		try:
			if any(i(*args) for i in filters):
				return
		except: pass
		self.lines += breaklines(newline)
	
	def printinput(self,string):
		_MOVE_CURSOR(DIM_Y-RESERVE_LINES+1)
		_DELETE_REST_OF_LINE(string)
		_MOVE_CURSOR(DIM_Y-RESERVE_LINES)
		#for some reason, it won't update input drawing (in IME) until I print something
		print('')
	
	def printblurb(self,string):
		_MOVE_CURSOR(DIM_Y-RESERVE_LINES+2)
		_DELETE_REST_OF_LINE(string)
		_MOVE_CURSOR(DIM_Y-RESERVE_LINES)
		print('')

	def printinfo(self,right,left):
		_MOVE_CURSOR(DIM_Y-RESERVE_LINES+3)
		self.bottom_edges[0] = left or self.bottom_edges[0]
		self.bottom_edges[1] = right or self.bottom_edges[1]
		room = DIM_X - len(self.bottom_edges[0]) - len(self.bottom_edges[1])
		print("\x1b[7m{}{}{}\x1b[0m".format(self.bottom_edges[0]," "*room,self.bottom_edges[1]),end="")
		_MOVE_CURSOR(DIM_Y-RESERVE_LINES)
		print('')

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

class listOverlay(overlayBase):
	replace = True
	def __init__(self,outList,drawOther = None):
		self.it = 0
		self.mode = 0
		self.list = outList
		if drawOther:
			setattr(self,"drawOther",drawOther)
	
	def display(self):
		_MOVE_CURSOR(0)
		_DELETE_REST_OF_LINE(_BOX_TOP())
		size = DIM_Y-RESERVE_LINES-2
		maxx = DIM_X-2
		#which portion of the lmaxyist is currently displaced
		partition = self.it//size
		#get the partition of the list we're at
		subList = self.list[size*partition:size*(partition+1)]
		#display
		i = 0
		for i,value in enumerate(subList):
			half = maxx//2
			#add an elipsis in the middle of the string if it can't be displayed; also, right justify
			value = (len(value) > maxx) and value[:half-3] + "..." + value[-half:] or value
			value += _CLEAR_FORMATTING
			if hasattr(self,'drawOther'):
				value = coloring(value)
				self.drawOther(value,i)
				value = value()

			if i+size*partition == self.it:
				value = _SELECTED(value)
			else:
				value += _CLEAR_FORMATTING

			_DELETE_REST_OF_LINE(_BOX_PART(value))
		#DIM_Y - RESERVE_LINES is the number of lines
		#fill out the rest of the overlay
		for j in range(size-len(subList)):
			_DELETE_REST_OF_LINE(_BOX_PART(" "))
		
		_DELETE_REST_OF_LINE(_BOX_BOTTOM())
	#predefined list iteration methods
	def onKEY_UP(self):
		self.it -= 1
		self.it %= len(self.list)
	def onKEY_DOWN(self):
		self.it += 1
		self.it %= len(self.list)
	#loop until escape
	def loop(self):
		self.display()
		while self.input() != -1:
			self.display()

class colorOverlay(overlayBase):
	replace = True
	names = ["Red","Green","Blue"]
	def __init__(self,initcolor = [127,127,127]):
		self.color = initcolor
		self.mode = 0
	#draw replacement
	def display(self):
		_MOVE_CURSOR(0)
		wide = (DIM_X-2)//3 - 1
		space = DIM_Y-RESERVE_LINES-7
		
		def centered(x,y):
			pre = x.rjust((wide+len(x))//2).ljust(wide)
			if y==self.mode: pre = _SELECTED(pre)
			return pre

		_DELETE_REST_OF_LINE(_BOX_TOP())
		for i in range(space):
			string = ""
			#draw on this line? (ratio of space alotted to line number = ratio of number to 255)
			for j in range(3):
				string += ((space-i)*255 < (self.color[j]*space)) and _COLOR_PAIRS[j+2] or ""
				string += " " * wide + _CLEAR_FORMATTING + " "
			#justify (including escape sequence length)
			just = _BOX_JUST(string)

			_DELETE_REST_OF_LINE(_BOX_NOFORM(string.rjust(just-1).ljust(just)))
		
		_DELETE_REST_OF_LINE(_BOX_PART(""))
		names = "{}{}{}".format(*[centered(j,i) for i,j in enumerate(self.names)])
		vals = "{}{}{}".format(*[centered(str(j),i) for i,j in enumerate(self.color)])
		_DELETE_REST_OF_LINE(_BOX_PART(names)) #4 lines
		_DELETE_REST_OF_LINE(_BOX_PART(vals)) #3 line
		_DELETE_REST_OF_LINE(_BOX_PART("")) #2 lines
		_DELETE_REST_OF_LINE(_BOX_PART(toHexColor(self.color).rjust(int(wide*1.5)+3))) #1 line
		_DELETE_REST_OF_LINE(_BOX_BOTTOM()) #last line
		
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

class scrollable:
	def __init__(self,width):
		self._text = ""
		self.pos = 0
		self.disp = 0
		self.history = []
		self.selhis = 0
		self.width = width
	#return the raw text contained within it
	def __call__(self):
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
		if (self.pos == self.disp and self.pos != 0) or self.pos - self.disp >= self.width:
			self.disp = max(0,min(self.pos-self.width+1,self.disp+dist))
	#display some text
	def display(self):
		text = self._text[:self.pos] + CHAR_CURSOR + self._text[self.pos:]
		text = text.replace("\n",r"\n").replace("\t",r"\t").replace("\r",r"\r")
		text = text[self.disp:self.disp+self.width]
		return text[-fitwordtolength(text[::-1],self.width)-1:]
	#history next
	def nexthist(self):
		if len(self.history) > 0:
			self.selhis += (self.selhis < (len(self.history)))
			self._text = self.history[-self.selhis]
			self.pos = len(self._text)
	#history prev
	def prevhist(self):
		if len(self.history) > 0:
			self.selhis -= (self.selhis > 0)
			#the next element or an empty string
			self._text = self.selhis and self.history[-self.selhis] or ""
			self.pos = len(self._text)
	#add new history entry
	def appendhist(self,new):
		self.history.append(new)
		self.history = self.history[-50:]
		self.selhis = 0
	

class main:
	lastlinks = []
	chatBot = None
	last = 0
	def __init__(self,screen):
		self.screen = screen
		self.text = scrollable(DIM_X-1)
		self.ins = []
		self.active = True
		self._chat = display()
		self.onresize()
		curses.curs_set(0)
	#=------------------------------=
	#|	DISPLAY FRONTENDS	|
	#=------------------------------=
	#system message
	def msgSystem(self, base):
		self._chat.append(_COLOR_PAIRS[1]+base+_CLEAR_FORMATTING)
		self._chat.display()
	#parse a message and color it
	def msgPost(self, post, *args):
		parseLinks(post,self.lastlinks)
		post = coloring(post)
		#empty dictionary to start
		for i in colorers:
			i(post,*args)
		#push the message and move the cursor back to the input window
		self._chat.append(post(),list(args))
		self._chat.display()
	#push a system message of the time
	def msgTime(self, numtime = None, predicate=""):
		dtime = time.strftime("%H:%M:%S",time.localtime(numtime or time.time()))
		self.msgSystem(predicate+dtime)
	#5 second blurb
	def newBlurb(self,message = ""):
		self.last = time.time()
		self._chat.printblurb(message)
	#update input
	def updateinput(self):
		self._chat.printinput(self.text.display())
	def updateinfo(self,right=None,left=None):
		self._chat.printinfo(right,left)
	#=------------------------------=
	#|	INPUT METHODS   	|
	#=------------------------------=
	#crux of input
	def input(self):
		try:
			chars = [self.screen.getch()]
		except KeyboardInterrupt:
			return -1
		#get as many chars as possible
		self.screen.nodelay(1)
		next = 0
		while next+1:
			next = self.screen.getch()
			chars.append(next)
		self.screen.nodelay(0)
		#control sequences
		curseAction = _CURSES_KEYS.get(chars[0])
		#delegate to display stack
		if self.ins:
			self = self.ins[-1]

		if curseAction and len(chars) == 2 and hasattr(self,"on"+curseAction):
			return getattr(self,"on"+curseAction)()

		if chars[0] in range(32,255) and hasattr(self,"oninput"):
			getattr(self,"oninput")(chars[:-1])
	#backspace
	def onbackspace(self):
		self.text.backspace()
	#enter
	def onenter(self):
		#if it's not just spaces
		text = self.text()
		if text.count(" ") != len(text):
			self.text.clear()
			self.text.appendhist(text)
			#if it's a command
			if text[0] == '~' and ' ' in text:
				try:
					command = commands[text[1:text.find(' ')]]
					command(self,text[text.find(' ')+1:].split(' '))
				finally:
					return
			self.chatBot.tryPost(text.replace(r'\n','\n'))
	#any other key
	def oninput(self,chars):
		#allow unicode input
		self.text.append(bytes(chars).decode())
	#escape
	def onescape(self):
		return -1
	#home
	def onKEY_SHOME(self):
		self.text.clear()
		self.shistory = 0
	#arrow keys
	def onKEY_LEFT(self):
		self.text.movepos(-1)
	def onKEY_RIGHT(self):
		self.text.movepos(1)
	def onKEY_UP(self):
		self.text.nexthist()
	def onKEY_DOWN(self):
		self.text.prevhist()
	def onKEY_HOME(self):
		self.text.home()
	def onKEY_END(self):
		self.text.end()
	#f2
	def onKEY_F2(self):
		#special wrapper to inject functionality for newlines in the list
		def select(me):
			def ret():
				if not len(self.lastlinks): return
				current = self.lastlinks[len(self.lastlinks) - 1 - me.it]
				if not me.mode:
					link_opener(self,current)
				else:
					paste(current)
				#exit
				return -1
			return ret
		
		#take out the protocol
		dispList = [i.replace("http://","").replace("https://","") for i in reversed(self.lastlinks)]
		#link number: link, but in reverse
		dispList = ["{}: {}".format(len(self.lastlinks)-i,j) for i,j in enumerate(dispList)] 
	
		box = listOverlay(dispList)
		box.addKeys({
			'enter':select(box),
			curses.KEY_RESIZE:resize(box,self)
		})
		self.addOverlay(box)
	#resize
	def onresize(self):
		global DIM_X,DIM_Y
		DIM_Y, DIM_X = self.screen.getmaxyx()
		self.text.width = DIM_X-1
		self._chat.redoLines()
		self._chat.display()
		self.updateinput()
		self.updateinfo()
	#=------------------------------=
	#|	Loop Frontends		|
	#=------------------------------=
	def loop(self):
		while self.active:
			if self.input() == -1:
				if not self.ins: break
				self.ins.pop()
				self._chat.overlay = (None if not self.ins else self.ins[-1])
				self.onresize()
				
			if self.ins:
				self._chat.display()
			else:
				self.updateinput()
		
	#threaded function that prints the current time every 10 minutes
	#also handles erasing blurbs
	def timeloop(self):
		i = 0
		while self.active:
			time.sleep(2)
			i+=1
			if time.time() - self.last > 4:
				self.newBlurb()
			#every 600 seconds
			if not i % 300:
				self.msgTime(time.time())
				i=0
	#=------------------------------=
	#|	Window Frontend 	|
	#=------------------------------=
	def addOverlay(self,new):
		self.ins.append(new)
		self._chat.overlay = new

#generic wrapper for redrawing listinputs
def resize(self,replace):
	def ret():
		global DIM_X,DIM_Y
		DIM_Y, DIM_X = self.screen.getmaxyx()
		self.text.width = DIM_X-1
	return ret

#DID SOMEONE SAY DECORATORS?
def onkey(keyname):
	def wrapper(func):
		if type(keyname) == str:
			setattr(main,"on"+keyname,func)
		else:
			setattr(main,"on"+_CURSES_KEYS[keyname],func)
	return wrapper

def colorer(func):
	colorers.append(func)

def chatfilter(func):
	filters.append(func)

def command(commandname):
	def wrapper(func):
		commands[commandname] = func
	return wrapper

def opener(extension):
	def wrap(func):
		setattr(link_opener,extension,staticmethod(func))
		#allow stacking wrappers
		return func
	return wrap

#clear formatting (reverse, etc)
@colorer
def removeFormatting(msg,*args):
	msg.append(_CLEAR_FORMATTING)
