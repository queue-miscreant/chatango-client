#!/usr/bin/env python3
#client.overlay.py
'''
Client module with single-byte curses input uses a
system of overlays, pulling input from the topmost
one. Output is not done with curses display, but various
different stdout printing calls.
'''
#TODO one last try for less lazy redolines?

try:
	import curses
except ImportError:
	raise ImportError("ERROR IMPORTING CURSES, is this running on Windows cmd?")
import sys
import os
import signal #redirect ctrl-z
import time
import asyncio
#from threading import Thread
from .display import *

__all__ =	["CHAR_COMMAND","start","soundBell","Box","command"
			,"OverlayBase","TextOverlay","ListOverlay","ColorOverlay"
			,"ColorSliderOverlay","InputOverlay","ConfirmOverlay"
			,"BlockingOverlay","MainOverlay","onDone","override","staticize"]

lasterr = None
RESERVE_LINES = 3

#escape has delay typically
os.environ.setdefault("ESCDELAY", "25")

#don't want to fire terminal stop, so just raise an exception to signal ctrl-z
class ControlZ(Exception): pass
def handler(signum, frame): raise ControlZ()
signal.signal(signal.SIGTSTP,handler)

#KEYBOARD KEYS------------------------------------------------------------------
_VALID_KEYNAMES = {
	"tab":		9
	,"enter":	10
	,"backspace":	127
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
		#better name
		if name == "dc": name = "delete"
		if name == "resize":
			continue
		elif name not in _VALID_KEYNAMES: #don't map KEY_BACKSPACE or KEY_ENTER
			_VALID_KEYNAMES[name] = getattr(curses,i)
#simplicity's sake
for i in range(32):
	#no, not +96 because that gives wrong characters for ^@ and ^_ (\x00 and \x1f)
	_VALID_KEYNAMES["^%s"%chr(i+64).lower()] = i
for i in range(32,256):
	_VALID_KEYNAMES[chr(i)] = i

#MOUSE BUTTONS
_MOUSE_BUTTONS = {
	"left":			curses.BUTTON1_PRESSED
	,"middle":		curses.BUTTON2_PRESSED
	,"right":		curses.BUTTON3_PRESSED
	,"wheel-up":	curses.BUTTON4_PRESSED
	,"wheel-down":	2**21
}
_MOUSE_MASK = 0
for i in _MOUSE_BUTTONS.values():
	_MOUSE_MASK |= i

del i

class KeyException(Exception):
	'''Exception for keys-related errors in client.overlay'''

def cloneKey(fro,to):
	'''Redirect one key to another. DO NOT USE FOR VALUES IN range(32,128)'''
	try:
		if isinstance(fro,str):
			fro = _VALID_KEYNAMES[fro]
		if isinstance(to,str):
			to = _VALID_KEYNAMES[to]
	except: raise KeyException("%s or %s is an invalid key name"%(fro,to))
	_KEY_LUT[fro] = to

#EXTENDABLE CONTAINERS----------------------------------------------------------
_commands = {}
_commandComplete = {}
_afterDone = []

#decorators for containers
def command(commandname,complete=[]):
	'''
	Add function as a command `commandname` with argument suggestion `complete`
	`complete` may either be a list or a function returning a list and a number
	that specifies where to start the suggestion from
	'''
	def wrapper(func):
		_commands[commandname] = func
		if complete:
			_commandComplete[commandname] = complete
			
	return wrapper
def onDone(func,*args):
	_afterDone.append((func,args))
	return func

#OVERLAY HELPERS------------------------------------------------------------------
CHAR_COMMAND = '`'

def centered(string,width):
	'''Center some text'''
	return string.rjust((width+len(string))//2).ljust(width)

class History:
	'''Container class for historical entries, similar to an actual shell'''
	#TODO when nexthist and prevhist are modified, save the current entry
	#use either modifications in TextOverlays with History or
	#pass in argument to prevhist/nexthist
	def __init__(self):
		self.history = []
		self._selhis = 0
		self.temp = ""
	def nexthist(self):
		'''Next historical entry (less recent)'''
		if self.history:
			self._selhis += (self._selhis < (len(self.history)))
			return self.history[-self._selhis]
		return ""
	def prevhist(self):
		'''Previous historical entry (more recent)'''
		if self.history:
			self._selhis -= (self._selhis > 0)
			#the next element or an empty string
			return self._selhis and self.history[-self._selhis] or ""
		return ""
	def append(self,new):
		'''Add new entry in history and maintain a size of at most 50'''
		self.history.append(new)
		self.history = self.history[-50:]
		self._selhis = 0

#DISPLAY/OVERLAY CLASSES----------------------------------------------------------
class SizeException(Exception):
	'''
	Exception for errors when trying to display an overlay.
	Should only be raised in an overlay's resize method,
	where if raised, the Main instance will not attempt to display.
	'''

CHAR_RETURN_CURSOR = "\x1b[?25h\x1b[u\n\x1b[A"
def _moveCursor(row = 0):
	'''Move the cursor to the row number specified'''
	print("\x1b[%d;f" % row,end=CLEAR_FORMATTING)
def soundBell():
	'''Sound console bell. Just runs `print("\a",end="")`'''
	print("\a",end="")

quitlambda = lambda x: -1
def staticize(func,*args):
	'''Staticizes a function and its arguments into a function with one argument.'''
	def ret(*garbage):			#garbage args
		return func(*args)
	ret.__doc__ = func.__doc__	#preserve documentation text
	return ret
def override(func,ret=0):
	'''Create a new function that returns `ret`. Use to override firing _post'''
	def retfunc(*args):
		func(*args)
		return ret
	retfunc.__doc__ = func.__doc__	#preserve documentation text
	return retfunc

class Box:
	'''
	Virtual class containing useful box shaping characters.
	To use, inherit from OverlayBase and this class simultaneously.
	'''
	CHAR_HSPACE = '─'
	CHAR_VSPACE = '│'
	CHAR_TOPL = '┌'
	CHAR_TOPR = '┐'
	CHAR_BTML = '└'
	CHAR_BTMR = '┘'
	
	def box_format(self,left,string,right,justchar = ' '):
		'''Format and justify part of box'''
		return "{}{}{}".format(left,self.box_just(string,justchar),right)
	def box_just(self,string,justchar = ' '):
		'''Pad string by column width'''
		if not isinstance(self.parent,Main):
			raise Exception("box object {} has no parent".format(self.__name__))
		return "{}{}".format(string,justchar*(self.parent.x-2-collen(string)))
	def box_noform(self,string):
		'''Returns a string in the sides of a box. Does not pad spaces'''
		return self.CHAR_VSPACE + string + self.CHAR_VSPACE
	def box_part(self,fmt = '') :
		'''Returns a properly sized string of the sides of a box'''
		return self.box_format(self.CHAR_VSPACE,fmt,self.CHAR_VSPACE)
	def box_top(self,fmt = ''):
		'''Returns a properly sized string of the top of a box'''
		return self.box_format(self.CHAR_TOPL,fmt,self.CHAR_TOPR,self.CHAR_HSPACE)
	def box_bottom(self,fmt = ''):
		'''Returns a properly sized string of the bottom of a box'''
		return self.box_format(self.CHAR_BTML,fmt,self.CHAR_BTMR,self.CHAR_HSPACE)

class OverlayBase:
	'''
	Virtual class that redirects input to callbacks and modifies a list
	of (output) strings. All overlays must descend from OverlayBase
	'''
	def __init__(self,parent):
		self.parent = parent		#parent
		self.index = None			#index in the stack
		self._keys = {
			27:	self._callalt		 #don't run post
			,curses.KEY_RESIZE:	lambda x: parent.resize() or 1 
			,curses.KEY_MOUSE:	self._callmouse
		}
		self._altkeys =	{-1: lambda: -1}
		self._mouse = {}
		if (hasattr(self,"_addOnInit")):
			self.addKeys(self._addOnInit)
	def __dir__(self):
		'''Get a list of keynames and their documentation'''
		ret = []
		for i,j in _VALID_KEYNAMES.items():
			#ignore named characters and escape, they're not verbose
			if i in ("^[","^i","^j",chr(127)): continue	
			docstring = ""
			formatString = ""
			if j in self._keys:
				docstring = self._keys[j].__doc__
				formatString = "{}: {}"
			elif j in self._altkeys:
				docstring = self._altkeys[j].__doc__
				formatString = "a-{}: {}"
			else: continue

			if docstring:
				docstring = docstring.replace('\n',"").replace('\t',"")
			else:
				docstring = "No documentation found"
			ret.append(formatString.format(i,docstring))
		ret.sort()
		return ret
	@asyncio.coroutine
	def __call__(self,lines):
		'''
		Overridable function. Modify lines by address (i.e lines[value])
		to display from main
		'''
		pass
	def _callalt(self,chars):
		'''Run a alt-key's callback'''
		return chars[0] in self._altkeys and self._altkeys[chars[0]]()
	def _callmouse(self,chars):
		'''Run a mouse's callback'''
		try:
			_,x,y,_,state = curses.getmouse()
			ret = state in self._mouse and self._mouse[state](x,y)
			chars = [i for i in chars if i != curses.KEY_MOUSE]
			if chars[0] != -1:
				return ret or self.runkey(chars)
			return ret
		except curses.error: pass
	def _post(self):
		'''
		Run after a keypress if the associated function returns boolean false
		If either the keypress or this returns boolean true, the overlay's
		parent redraws
		'''
		return 1
	def runkey(self,chars):
		'''
		Run a key's callback. This expects a single argument: a list of
		numbers terminated by -1
		'''
		ret = 0
		try:
			char = _KEY_LUT[chars[0]]
		except: char = chars[0]
			
		#ignore the command character and trailing -1
		#second clause ignores heading newlines
		if (char in self._keys) and (char == 27 or len(chars) <= 2 or char > 255):
			return self._keys[char](chars[1:] or [-1]) or self._post()
		if -1 in self._keys and (char in (9,10,13) or char in range(32,255)):
			return self._keys[-1](chars[:-1]) or self._post()
	@asyncio.coroutine
	def resize(self,newx,newy):
		'''Overridable function. On resize event, all added overlays have this called'''
		pass
	#frontend methods----------------------------
	def add(self):
		'''Safe method to run when the overlay needs to be added. '''
		self.parent.addOverlay(self)
	def remove(self):
		'''Safe method to run when the overlay needs to be removed'''
		self.parent.popOverlay(self)
	def swap(self,new):
		'''Safe method to pop overlay and add new one in succession.'''
		self.remove()
		new.add()
	def addKeys(self,newFunctions = {},areMethods = 0):
		'''
		Nice method to add keys after instantiation. Support for
		a- (alt keys), or curses keynames.
		'''
		for i,j in newFunctions.items():
			if isinstance(i,str):
				if not i.lower().find("a-"):
					i = i[2:]
					if i in _VALID_KEYNAMES:
						i = _VALID_KEYNAMES[i]
						if areMethods:
							self._altkeys[i] = j
						else:
							self._altkeys[i] = lambda: j(self)
						continue
					else: raise KeyException("key alt-{} invalid".format(i))
				elif not i.lower().find("mouse-"):
					i = i[6:]
					if i in _MOUSE_BUTTONS:
						i = _MOUSE_BUTTONS[i]
						if areMethods:
							self._mouse[i] = j
						else:
							self._mouse[i] = lambda x,y: j(self,x,y)
						continue
					else: raise KeyException("key mouse-{} invalid".format(i))
				else:
					try:
						i = _VALID_KEYNAMES[i]
					except: raise KeyException("key {} invalid".format(i))
			if areMethods:
				self._keys[i] = staticize(j)
			else:
				self._keys[i] = staticize(j,self)

	@classmethod
	def addKey(cls,key):
		if not hasattr(cls,"_addOnInit"):
			cls._addOnInit = {}
		def ret(func):
			cls._addOnInit[key] = func
		return ret

class TextOverlay(OverlayBase):
	'''Virtual overlay with text input (at bottom of screen)'''
	def __init__(self,parent = None):
		super(TextOverlay, self).__init__(parent)
		self.text = parent.addScrollable()
		#ASCII code of sentinel char
		self._sentinel = 0
		self._keys.update({
			-1:				self._input
			,9:				staticize(self.text.complete)
			,26:			staticize(self.text.undo)
			,127:			staticize(self.text.backspace)
			,curses.KEY_BTAB:	staticize(self.text.backcomplete)
			,curses.KEY_DC:		staticize(self.text.delchar)
			,curses.KEY_SHOME:	staticize(self.text.clear)
			,curses.KEY_RIGHT:	staticize(self.text.movepos,1)
			,curses.KEY_LEFT:	staticize(self.text.movepos,-1)
			,curses.KEY_HOME:	staticize(self.text.home)
			,curses.KEY_END:	staticize(self.text.end)
			,520:				staticize(self.text.delnextword)
		})
		self._keys[curses.KEY_LEFT].__doc__ = "Move cursor left"
		self._keys[curses.KEY_RIGHT].__doc__ = "Move cursor right"
		self._altkeys.update({
			ord('h'):		self.text.wordback
			,ord('l'):		self.text.wordnext
			,127:			self.text.delword
			,330:			self.text.delnextword	#tmux alternative
		})
	def _input(self,chars):
		'''
		Safe appending to scrollable. Takes out invalid ASCII (chars above 256)
		that might get pushed by curses. If self.sentinel is not empty, the
		text contained is empty, and it's the sentinel character alone, fire
		_onSentinel 
		'''
		if self._sentinel and not str(self.text) and len(chars) == 1 and \
			chars[0] == self._sentinel:
			return self._onSentinel()
		#allow unicode input with the bytes().decode()
		return self.text.append(bytes([i for i in chars if i<256]).decode())
	def _onSentinel(self):
		'''Function run when sentinel character is typed at the beginning of the line'''
		pass
	@asyncio.coroutine
	def resize(self,newx,newy):
		'''Adjust scrollable on resize'''
		self.text.setwidth(newx)
	def remove(self):
		'''Pop scrollable on remove'''
		super().remove()
		self.parent.popScrollable(self.text)
	def controlHistory(self,history,scroll):
		'''
		Add key definitions for standard controls for History `history`
		and scrollable `scroll`
		'''
		nexthist = lambda: scroll.setstr(history.nexthist())
		prevhist = lambda: scroll.setstr(history.prevhist())
		#preserve docstrings for getKeynames
		nexthist.__doc__ = history.nexthist.__doc__
		prevhist.__doc__ = history.prevhist.__doc__
		self._keys.update({
			curses.KEY_UP:		staticize(nexthist)
			,curses.KEY_DOWN:	staticize(prevhist)
		})

class ListOverlay(OverlayBase,Box):
	'''Display a list of objects, optionally drawing something additional'''
	replace = True
	def __init__(self,parent,outList,drawOther = None,modes = [""]):
		super(ListOverlay, self).__init__(parent)
		self.it = 0
		self.mode = 0
		self.list = outList
		self._drawOther = drawOther
		self._modes = modes
		self._nummodes = len(modes)
		self._numentries = len(self.list)
		self._keys.update(
			{ord('j'):	staticize(self.increment,1) #V I M
			,ord('k'):	staticize(self.increment,-1)
			,ord('l'):	staticize(self.chmode,1)
			,ord('h'):	staticize(self.chmode,-1)
			,ord('q'):	quitlambda
			,curses.KEY_DOWN:	staticize(self.increment,1)
			,curses.KEY_UP:		staticize(self.increment,-1)
			,curses.KEY_RIGHT:	staticize(self.chmode,1)
			,curses.KEY_LEFT:	staticize(self.chmode,-1)
		})
		def tryEnter():
			'''Try to run the function bound to enter'''
			selectFun = self._keys.get(10)
			if callable(selectFun):
				return selectFun()
		def click(_,y):
			'''Manipulate self.it and tryEnter'''
			#y in the list
			size = self.parent.y - 2
			#borders
			if not y in range(1,size+1): return
			newit = (self.it//size)*size + (y - 1)
			if newit > len(self.list): return
			self.it = newit
			return tryEnter()
		self._mouse.update(
			{_MOUSE_BUTTONS["left"]:		click
			,_MOUSE_BUTTONS["right"]:		override(click)
			,_MOUSE_BUTTONS["middle"]:		staticize(tryEnter)
			,_MOUSE_BUTTONS["wheel-up"]:	staticize(self.increment,-1)
			,_MOUSE_BUTTONS["wheel-down"]:	staticize(self.increment,1)
		})
	@asyncio.coroutine
	def __call__(self,lines):
		'''
		Display a list in a box. If too long, entries are trimmed
		to include an ellipsis
		'''
		lines[0] = self.box_top()
		size = self.parent.y-2
		maxx = self.parent.x-2
		#worst case column: |(value[0])...(value[-1])|
		#				    1    2     345  6	     7
		#worst case rows: |(list member)|(RESERVED)
		#				  1	2			3
		if size < 1 or maxx < 5:
			raise SizeException()
		#which portion of the list is currently displaced
		partition = (self.it//size)*size
		#get the partition of the list we're at, pad the list
		subList = self.list[partition:partition+size]
		subList = subList + ["" for i in range(size-len(subList))]
		#display lines
		for i,value in enumerate(subList):
			half = maxx//2
			#add an elipsis in the middle of the string if it 
			#can't be displayed and, right justify
			row = (len(value) > maxx) and value[:max(half,1)] + \
				"..." + value[min(-half+3,-1):] or value
			row = Coloring(self.box_just(row))
			if value and self._drawOther is not None:
				self._drawOther(row,i+partition,len(self.list))
			if i+partition == self.it:
				row.addGlobalEffect(0)
			lines[i+1] = self.box_noform(format(row))
		lines[-1] = self.box_bottom(self._modes[self.mode])
		return lines
	#predefined list iteration methods
	def increment(self,amt):
		'''Move self.it by amt'''
		if not self._numentries: return
		self.it += amt
		self.it %= self._numentries
	def chmode(self,amt):
		'''Move to mode amt over, with looparound'''
		self.mode = (self.mode + amt) % self._nummodes

class ColorOverlay(ListOverlay,Box):
	'''Display 3 bars for red, green, and blue. Allows exporting of color as hex'''
	replace = True
	_SELECTIONS = ["normal","shade","tint","grayscale"]
	_COLOR_LIST = ["red","orange","yellow","light green","green","teal",
		"cyan","turquoise","blue","purple","magenta","pink","color sliders"]

	def __init__(self,parent,initcolor=None):
		self._spectrum = self._genspectrum()
		super(ColorOverlay, self).__init__(parent,self._COLOR_LIST,
				self.drawColors, self._SELECTIONS)
		#parse initcolor
		self.initcolor = [127,127,127]
		if type(initcolor) is str and len(initcolor) == 6:
			initcolor = [int(initcolor[i*2:(i+1)*2],16) for i in range(3)]
		if type(initcolor) is list and len(initcolor) == 3:
			self.initcolor = initcolor
			divs = [divmod(i*6/255,1) for i in initcolor]
			#if each error is low enough to be looked for
			if all([i[1] < .05 for i in divs]):
				for i,j in enumerate(self._spectrum[:3]):
					find = j.index([k[0] for k in divs])
					if find+1:
						self.it = find
						self.mode = i
						break
				self.it = len(self._COLOR_LIST)-1
			else:
				self.it = len(self._COLOR_LIST)-1

	def drawColors(self,string,i,maxval):
		#4 is reserved for color sliders
		if self.parent.two56 and i < 12:
			color = None
			which = self._spectrum[self.mode][i]
			if self.mode == 3: #grayscale
				color = (which * 2) + 232
			else:
				color = sum(map(lambda x,y:x*y,which,[36,6,1])) + 16
			string.insertColor(-1,self.parent.two56start + color)
			string.effectRange(-1,0,0)

	def getColor(self,typ = str):
		which = self._spectrum[self.mode][self.it]
		color = [int(i*255/5) for i in which] 
		if typ is str:
			return ''.join(['%02x' % i for i in color])
		return color

	def openSliders(self,selectFunction):
		furtherInput = ColorSliderOverlay(self.parent,self.initcolor)
		furtherInput.addKeys({"enter": selectFunction})
		furtherInput.add()

	@staticmethod
	def _genspectrum():
		init = [0,2]
		final = [5,2]
		rspec = [(5,g,0) for g in init]
		yspec = [(r,5,0) for r in final]
		cspec = [(0,5,b) for b in init]
		bspec = [(0,g,5) for g in final]
		ispec = [(r,0,5) for r in init]
		mspec = [(5,0,b) for b in final]

		spectrum = [item for i in [rspec,yspec,cspec,bspec,ispec,mspec] for item in i]

		shade = [(max(0,i[0]-1),max(0,i[1]-1),max(0,i[2]-1)) for i in spectrum]
		tint = [(min(5,i[0]+1),min(5,i[1]+1),min(5,i[2]+1)) for i in spectrum]
		grayscale = range(12)

		return [spectrum,shade,tint,grayscale]

class ColorSliderOverlay(OverlayBase,Box):
	'''Display 3 bars for red, green, and blue. Allows exporting of color as hex'''
	replace = True
	NAMES = ["Red","Green","Blue"]
	def __init__(self,parent,initcolor = [127,127,127]):
		super(ColorSliderOverlay, self).__init__(parent)
		#allow setting from hex value
		if isinstance(initcolor,str):
			self.setHex(initcolor)
		else:
			self.color = initcolor
		self._rgb = 0
		self._keys.update(
			{ord('q'):		quitlambda
			,ord('k'):		staticize(self.increment,1)
			,ord('j'):		staticize(self.increment,-1)
			,ord('l'):		staticize(self.chmode,1)
			,ord('h'):		staticize(self.chmode,-1)
			,curses.KEY_UP:		staticize(self.increment,1)
			,curses.KEY_DOWN:	staticize(self.increment,-1)
			,curses.KEY_PPAGE:	staticize(self.increment,10)
			,curses.KEY_NPAGE:	staticize(self.increment,-10)
			,curses.KEY_HOME:	staticize(self.increment,255)
			,curses.KEY_END:	staticize(self.increment,-255)
			,curses.KEY_RIGHT:	staticize(self.chmode,1)
			,curses.KEY_LEFT:	staticize(self.chmode,-1)
		})
	@asyncio.coroutine
	def __call__(self,lines):
		'''Display 3 bars, their names, values, and string in hex'''
		wide = (self.parent.x-2)//3 - 1
		space = self.parent.y-7
		if space < 1 or wide < 5: #green is the longest name
			raise SizeException()
		lines[0] = self.box_top()
		for i in range(space):
			string = ""
			#draw on this line (ratio of space alotted to line number = ratio of number to 255)
			for j in range(3):
				if ((space-i)*255 < (self.color[j]*space)):
					string += getColor(rawNum(j+2))
				string += ' ' * wide + CLEAR_FORMATTING + ' '
			#justify (including escape sequence length)
			lines[i+1] = self.box_noform(self.box_just(string))
		sep = self.box_part("")
		lines[-6] = sep
		names,vals = "",""
		for i in range(3):
			if i == self._rgb:
				names += SELECT
				vals += SELECT
			names += centered(self.NAMES[i],wide) + CLEAR_FORMATTING
			vals += centered(str(self.color[i]),wide) + CLEAR_FORMATTING
		lines[-5] = self.box_part(names) #4 lines
		lines[-4] = self.box_part(vals) #3 line
		lines[-3] = sep #2 lines
		lines[-2] = self.box_part(self.getHex().rjust(int(wide*1.5)+3)) #1 line
		lines[-1] = self.box_bottom() #last line
	#predefined self-traversal methods
	def increment(self,amt):
		'''Increase the selected color by amt'''
		self.color[self._rgb] = max(0,min(255, self.color[self._rgb] + amt))
	def chmode(self,amt):
		'''Go to the color amt to the right'''
		self._rgb = (self._rgb + amt) % 3
	def getHex(self):
		'''Get self.color in hex form'''
		return ''.join([hex(i)[2:].rjust(2,'0') for i in self.color])
	def setHex(self,hexstr):
		'''Set self.color from hex'''
		self.color = [int(hexstr[2*i:2*i+2],16) for i in range(3)]

class InputOverlay(TextOverlay,Box):
	'''Replacement for input(). '''
	replace = False
	def __init__(self,parent,prompt,password = False,end = False):
		super(InputOverlay, self).__init__(parent)
		self._done = False
		self._prompt = Coloring(prompt)
		self._prompts,self._numprompts = self._prompt.breaklines(parent.x-2)
		self.text.password = password
		self._end = end
		self._keys.update({
			10:		staticize(self._finish)
			,127:	staticize(self._backspacewrap)
		})
		self._altkeys.update({
			None:	self._stop
		})
	@asyncio.coroutine
	def __call__(self,lines):
		'''Display the text in roughly the middle, in a box'''
		start = self.parent.y//2 - self._numprompts//2
		end = self.parent.y//2 + self._numprompts
		lines[start] = self.box_top()
		for i,j in enumerate(self._prompts):
			lines[start+i+1] = self.box_part(j)
		#preserve the cursor position save
		lines[end+1] = self.box_bottom()
	def _backspacewrap(self):
		'''Backspace a char, or quit out if there are no chars left'''
		if not str(self.text): return -1
		self.text.backspace()
	def _stop(self):
		'''Premature stop. _done is not set'''
		return -1
	def _finish(self):
		'''Regular stop (i.e, with enter)'''
		self._done = True
		if hasattr(self,"ondone"): self.ondone(str(self.text))
		return -1
	def remove(self):
		'''Make parent inactive if the first overlay and prematurely stopped'''
		if not self.index and not self._done:
			self.parent.active = False
		super().remove()
	@asyncio.coroutine
	def resize(self,newx,newy):
		'''Resize prompts'''
		super().resize(newx,newy)
		self._prompts,self._numprompts = self._prompt.breaklines(parent.x-2)

	def waitForInput(self):
		'''All input is non-blocking, so we have to poll from another thread'''
		while not self._done:
			time.sleep(.1)
		return str(self.text)
	def runOnDone(self,func):
		'''Set function to run after valid poll'''
		self.ondone = func

class CommandOverlay(TextOverlay):
	'''Overlay to run commands. Commands are run in separate threads'''
	replace = False
	history = History()	#global command history
	def __init__(self,parent,caller = None):
		super(CommandOverlay,self).__init__(parent)
		self._sentinel = ord(CHAR_COMMAND)
		self.caller = caller
		self.text.setnonscroll(CHAR_COMMAND)
		self.text.completer.addComplete(CHAR_COMMAND,_commands)
		for i,j in _commandComplete.items():
			self.text.addCommand(i,j)
		self.controlHistory(self.history,self.text)
		self._keys.update({
			10:		staticize(self._run)
			,127:	staticize(self._backspacewrap)
		})
		self._altkeys.update({
			127:	lambda: -1
		})
	@asyncio.coroutine
	def __call__(self,lines):
		lines[-1] = "COMMAND"
	def _onSentinel(self):
		#TODO just assign this a reference to the MainOverlay that called it
		if self.caller:
			#get the highest mainOverlay
			self.caller.text.append(CHAR_COMMAND)
		return -1
	def _backspacewrap(self):
		'''Backspace a char, or quit out if there are no chars left'''
		if not str(self.text): return -1
		self.text.backspace()
	def _run(self):
		'''Run command'''
		text = str(self.text)
		self.history.append(text)
		args = text.split(' ')
		if args[0] not in _commands:
			self.parent.newBlurb("Command \"{}\" not found".format(args[0]))
			return -1
		command = _commands[args[0]]
		try:
			add = command(self.parent,*args[1:])
			if isinstance(add,OverlayBase):
				self.swap(add)
				return
		except Exception as exc:
			self.parent.newBlurb(
				'an error occurred while running command {}'.format(args[0]))
			dbmsg('{} occurred in command {}: {}'.format(
				type(exc).__name__,args[0], exc))
		except KeyboardInterrupt: pass
		return -1

class EscapeOverlay(OverlayBase):
	'''Overlay for redirecting input after \ is pressed'''
	replace = False
	def __init__(self,parent,scroll):
		super(EscapeOverlay, self).__init__(parent)
		self._keys.update({
			-1:		quitlambda
			,9:		override(staticize(scroll.append,'\t'),-1)
			,10:	override(staticize(scroll.append,'\n'),-1)
			,ord('n'):	override(staticize(scroll.append,'\n'),-1)
			,ord('\\'):	override(staticize(scroll.append,'\\'),-1)
			,ord('t'):	override(staticize(scroll.append,'\t'),-1)
		})

class ConfirmOverlay(OverlayBase):
	'''Overlay to confirm selection confirm y/n (no slash)'''
	replace = False
	def __init__(self,parent,confirmfunc):
		super(ConfirmOverlay, self).__init__(parent)
		def confirmed(*args):
			confirmfunc()
			self.parent.releaseBlurb()
			return -1
		self._keys.update( #run these in order
			{ord('y'):	confirmed
			,ord('n'):	override(staticize(self.parent.releaseBlurb),-1)
		})

class BlockingOverlay(OverlayBase):
	'''Block until any input is received'''
	replace = False
	def __init__(self,parent,confirmfunc,tag=""):
		super(BlockingOverlay, self).__init__(parent)
		self.tag = tag
		self._keys.update({-1: override(staticize(confirmfunc),-1)})

	def add(self):
		if self.tag:
			for i in self.parent.getOverlaysByClassName(type(self).__name__):
				#don't add overlays with the same tag
				if i.tag == self.tag: return
		super(BlockingOverlay, self).add()

class MainOverlay(TextOverlay):
	'''
	Overlay that can push and select messages, and has an input box.
	Optionally pushes time messages every 10 minutes and refreshes 
	blurbs every few seconds
	'''
	replace = True
	_MSGSPLIT = '\x1b'	#sequence between messages to draw reversed
	_INDENT = "    "	#indent for breaklines
	_monitors = {}
	def __init__(self,parent,pushtimes = True):
		super(MainOverlay, self).__init__(parent)
		self._sentinel = ord(CHAR_COMMAND)
		self._pushtimes = pushtimes
		self.history = History()
		self.clear()
		self.controlHistory(self.history,self.text)
		self._keys.update({
			ord('\\'):		staticize(self._replaceback)
		})
		self._altkeys.update({
			ord('k'):		self.selectup
			,ord('j'):		self.selectdown
		})
		self._mouse.update({
			_MOUSE_BUTTONS["wheel-up"]:		staticize(self.selectup)
			,_MOUSE_BUTTONS["wheel-down"]:	staticize(self.selectdown)
		})
		examiners = self._monitors.get(type(self).__name__)
		if examiners is not None:
			self._examine = examiners
		else:
			self._examine = []

	@asyncio.coroutine
	def __call__(self,lines):
		'''Display messages'''
		select = SELECT_AND_MOVE
		#seperate traversals
		selftraverse,linetraverse = -1,-2
		lenself, lenlines = len(self._lines),len(lines)
		msgno = 0
		#go backwards by default
		direction = -1
		#if we need to go forwards
		if self._linesup-self._unfiltup-self._innerheight >= lenlines:
			direction = 1
			msgno = self._unfiltup
			selftraverse,linetraverse = -self._linesup+self._innerheight,-lenlines
			lenself, lenlines = -1,-2
		#traverse list of lines
		while (selftraverse*direction) <= lenself and \
		(linetraverse*direction) <= lenlines:
			if self._lines[selftraverse] == self._MSGSPLIT:
				selftraverse += direction #disregard this line
				msgno -= direction #count lines down downward, up upward
				continue
			reverse = (msgno == self._unfiltup) and select or ""
			lines[linetraverse] = reverse + self._lines[selftraverse]
			selftraverse += direction
			linetraverse += direction
		lines[-1] = Box.CHAR_HSPACE*self.parent.x

	#method overloading---------------------------------------------------------
	def _onSentinel(self):
		'''Input some text, or enter CommandOverlay when CHAR_CURSOR typed'''
		CommandOverlay(self.parent,self).add()
	def _post(self):
		'''Stop selecting'''
		if self._selector:
			self._selector = 0
			self._linesup = 0
			self._unfiltup = 0
			self._innerheight = 0
			self.parent.updateinput()	#put the cursor back
			return 1
	def add(self):
		'''Start timeloop and add overlay'''
		super().add()
		if self._pushtimes:
			times = Thread(target=self._timeloop)
			times.daemon = True
			times.start()
	def remove(self):
		'''Quit timeloop (if it hasn't already exited). Exit client if last overlay.'''
		super().remove()
		self._pushtimes = False
		if not self.index:
			self.parent.active = False
	@asyncio.coroutine
	def resize(self,newx,newy):
		'''Resize scrollable and maybe draw lines again if width changed'''
		super().resize(newx,newy)
		if newx != self.parent.x:
			self.redolines(newx,newy)

	def clear(self):
		'''Clear all lines and messages'''
		self.canselect = True
		#these two REALLY should be private
		self._allMessages = []
		self._lines = []
		#these too because they select the previous two
		self._selector = 0			#messages from the bottom
		self._unfiltup = 0			#ALL messages from the bottom, incl filtered
		self._linesup = 0			#lines up from the bottom, incl MSGSPLIT
		self._innerheight = 0		#inner message height, for ones too big
		#recolor
		self._lastrecolor = 0		#last recolor time
		self._messageAdjust = 0		#adjuster for resize
		self._linesAdjust = 0		#adjuster for lines
	#VIRTUAL FILTERING------------------------------------------
	@classmethod
	def examineMessage(cls,className):
		'''
		Wrapper for a function that monitors messages. Such function may perform some
		effect such as pushing a new message or alerting the user
		'''
		def wrap(func):
			if cls._monitors.get(className) is None:
				cls._monitors[className] = []
			cls._monitors[className].append(func)
		return wrap
	def colorizeMessage(self, msg, *args):
		'''
		Virtual function. Overload to apply some transformation on argument
		`msg`, which is a client.Coloring object. Arguments are left generic
		so that the user can define message args
		'''
		return msg
	def filterMessage(self, *args):
		'''
		Virtual function called to see if a message can be displayed. If False,
		the message can be displayed. Otherwise, the message is pushed to
		_allMessages without drawing to _lines. Arguments are left generic so
		that the user can define message args
		'''
		return False

	def _timeloop(self):
		'''Prints the current time every 10 minutes. Also handles erasing blurbs'''
		i = 0
		parent = self.parent
		while self._pushtimes:
			time.sleep(2)
			i+=1
			if time.time() - parent.last > 4:	#erase blurbs
				parent.newBlurb()
			#every 600 seconds
			if not i % 300:
				self.msgTime(time.time())
				i=0
	def _replaceback(self):
		'''Add a newline if the next character is n, or a tab if the next character is t'''
		EscapeOverlay(self.parent,self.text).add()

	#MESSAGE PUSHING BACKEND-----------------------------------
	def _prepend(self,newline,args = None,isSystem = False):
		'''Prepend new message. Use msgPrepend instead'''
		#run filters early so that the message can be selected up to properly
		msg = [newline, args, isSystem, not self.filterMessage(*args)
			,self._lastrecolor, len(self._allMessages)]
		self._allMessages.insert(0,msg)
		#we actually need to draw it
		if (self._linesup - self._unfiltup) < (self.parent.y-1):
			#ignore the hacky thing I'm using lines length for
			if isSystem or msg[3]:
				a,b = newline.breaklines(self.parent.x,self._INDENT)
				a.append(self._MSGSPLIT)
				self._lines = a + self._lines
				msg[3] = b

		return msg[-1]
		
	def _append(self,newline,args = None,isSystem = False):
		'''Add new message. Use msgPost instead'''
		#undisplayed messages have length zero
		msg = [newline,args,isSystem,0,self._lastrecolor,len(self._allMessages)]
		self._allMessages.append(msg)
		#before we filter it
		self._selector += (self._selector>0)
		#run filters
		if (not isSystem) and self.filterMessage(*args):
			return msg[-1]
		a,b = newline.breaklines(self.parent.x,self._INDENT)
		a.append(self._MSGSPLIT)
		self._lines += a
		msg[3] = b
		#keep the right message selected
		if self._selector:
			self._linesup += b+1
			self._unfiltup += 1
		return msg[-1]

	#MESSAGE SELECTION----------------------------------------------------------
	def _getnextmessage(self,step):
		'''Backend for selecting message'''
		#scroll back up the message
		if step > 0 and self._innerheight:
			self._innerheight -= 1
			return 0
		tooBig = self._allMessages[-self._selector][3] - (self.parent.y-1)
		#downward, so try to scroll the message downward
		if step < 0 and tooBig > 0:
			if self._innerheight < tooBig:
				self._innerheight += 1
				return 0
		#otherwise, try to find next message
		select = self._selector+step
		addlines = 0
		#get the next non-filtered message
		while not addlines and select <= len(self._allMessages):
			addlines = self._allMessages[-select][3]
			select += step
		#if we're even "going" anywhere
		if select - step - self._selector:
			self._selector = max(0,select - step)
			self._unfiltup = max(0,self._unfiltup + step)
			self._innerheight = 0
		return addlines
	def _maxselect(self):
		soundBell()
	def selectup(self):
		'''Select message up'''
		if not self.canselect: return 1
		#go up the number of lines of the "next" selected message
		upmsg = self._getnextmessage(1)
		#but only if there is a next message
		if not upmsg: self._maxselect()
		else:
			self._linesup += upmsg+1
			if self._linesup > len(self._lines):	#don't forget the new lines
				cur = self._allMessages[-self._selector]
				if (not cur[2]) and cur[4] < self._lastrecolor:
					self.colorizeMessage(cur[0],*cur[1])
				a,b = cur[0].breaklines(self.parent.x,self._INDENT)
				a.append(self._MSGSPLIT)
				self._lines = a + self._lines
				cur[3] = b
				#IMPERATIVE to get the correct length up
				self._linesup += (b - upmsg)
		return 1
	def selectdown(self):
		'''Select message down'''
		if not self.canselect: return 1
		#go down the number of lines of the currently selected message
		curLines = self._allMessages[-self._selector][3]
		downMsg = self._getnextmessage(-1)
		if downMsg:
			self._linesup = max(0,self._linesup-curLines-1)
		if not self._selector:
			self.parent.updateinput()	#move the cursor back
		return 1

	#FRONTENDS--------------------------------------------------
	def isselecting(self):
		'''Whether a message is selected or not'''
		return bool(self._selector)
	def getselected(self):
		'''
		Frontend for getting the selected message. Returns a 6-list:
		[0]: the message (in a coloring object), [1] an argument tuple,
		[2]: if it's a system message, [3] how many lines it occupies,
		[4]: the last time the message was colored, [5]: its ID in _allMessages
		'''
		return self._allMessages[-self._selector]

	def clickMessage(self,x,y):
		'''Get the message at position x,y and depth into the string'''
		if y >= self.parent.y-1: return
		#go up or down
		direction = -1
		msgNo = -1
		height = 0
		if self._linesup-self._unfiltup >= self.parent.y:
			direction = 1
			msgNo = -self._selector
		else:
			#"height" from the top
			y = self.parent.y - y
		#find message until we exceed the height
		while msgNo >= -len(self._allMessages) and height < (y+direction):
			height += self._allMessages[msgNo][3]
			msgNo += direction
		msg = self._allMessages[msgNo-direction]
		#do some logic for finding the line clicked
		linesDeep = (y-height)*direction + 1
		firstLine = (height * direction) + msgNo + 1
		if direction + 1:
			firstLine -= msg[3] + self._linesup - self._selector + 2
			linesDeep += msg[3] - 1 + self._innerheight
		#adjust the position
		pos = x 
		for i in range(linesDeep):
			pos += collen(self._lines[i+firstLine]) - len(self._INDENT)
		if x < len(self._INDENT):
			pos += len(self._INDENT) - x
		return msg,pos
	#REAPPLY METHODS-----------------------------------------------------------
	@asyncio.coroutine
	def redolines(self, width = None, height = None):
		'''
		Redo lines, if current lines does not represent the unfiltered messages
		or if the width has changed
		'''
		if width is None: width = self.parent.x
		if height is None: height = self.parent.y
		newlines = []
		numup,nummsg = 0,1
		#while there are still messages to add (to the current height)
		#feels dirty and slow, but this will also resize all messages below
		#the selection
		while (nummsg <= self._selector or numup < height) and \
			nummsg <= len(self._allMessages):
			i = self._allMessages[-nummsg]
			#check if the message should be drawn
			if (not i[2]) and self.filterMessage(*i[1]):
				i[3] = 0
				nummsg += 1
				continue
			a,b = i[0].breaklines(width,self._INDENT)
			a.append(self._MSGSPLIT)
			newlines = a + newlines
			i[3] = b
			numup += b
			if nummsg == self._selector: #invalid always when self._selector = 0
				self._linesup = numup + self._unfiltup
			nummsg += 1
		self._lines = newlines
		self.canselect = True

	@asyncio.coroutine
	def recolorlines(self):
		'''Re-apply colorizeMessage and redraw all visible lines'''
		self._lastrecolor = time.time()
		width = self.parent.x
		height = self.parent.y
		newlines = []
		numup,nummsg = 0,1
		while (numup < height or nummsg <= self._selector) and \
			nummsg <= len(self._allMessages):
			i = self._allMessages[-nummsg]
			if not i[2]:	#don't decolor system messages
				i[0].clear()
				self.colorizeMessage(i[0],*i[1])
				i[4] = self._lastrecolor
			nummsg += 1
			if i[3]: #unfiltered (non zero lines)
				a,b = i[0].breaklines(width,self._INDENT)
				a.append(self._MSGSPLIT)
				newlines = a + newlines
				i[3] = b
				numup += b
		self._lines = newlines
		self.parent.display()
	#MESSAGE ADDITION----------------------------------------------------------
	#TODO coroutinize
	def msgSystem(self, base):
		'''System message'''
		base = Coloring(base)
		base.insertColor(0,rawNum(1))
		self._append(base,None,True)
		self.parent.display()
	def msgTime(self, numtime = None, predicate=""):
		'''Push a system message of the time'''
		dtime = time.strftime("%H:%M:%S",time.localtime(numtime or time.time()))
		self.msgSystem(predicate+dtime)
	def msgPost(self,post,*args):
		'''Parse a message, apply colorizeMessage, and append'''
		post = Coloring(post)
		self.colorizeMessage(post,*args)
		ret = self._append(post,list(args))
		for i in self._examine:
			i(self,post,*args)
		self.parent.display()
		return ret
	def msgPrepend(self,post,*args):
		'''Parse a message, apply colorizeMessage, and prepend'''
		post = Coloring(post)
		self.colorizeMessage(post,*args)
		ret = self._prepend(post,list(args))
		self.parent.display()
		return ret
	def msgDelete(self,number):
		for i,j in enumerate(reversed(self._allMessages)):
			if number == j[-1]:
				del self._allMessages[-i-1]
				self.redolines()
				self.parent.display()

class _NScrollable(ScrollSuggest):
	'''
	A scrollable that expects a Main object as parent so that it 
	can run Main.updateinput()
	'''
	def __init__(self,width,parent,index):
		super(_NScrollable, self).__init__(width)
		self.parent = parent
		self.index = index
	def _onchanged(self):
		super(_NScrollable, self)._onchanged()
		self.parent.updateinput()

#MAIN CLIENT--------------------------------------------------------------------
class _Schedule:
	'''Simple class for scheduling displays'''
	def __init__(self):
		self._scheduler = []
		self._taskno = 0
		self._debounce = False
	def __call__(self,func,*args):
		'''Run a function. If debounce is True, schedule it'''
		if self._debounce:
			self._scheduler.append((func,args))
			return True
		self._bounce(True)
		func(*args)
		self._bounce(False)
	def _bounce(self,newbounce):
		'''
		Change the value of debounce. If bounce is on a falling edge,
		run queued functions	
		'''
		prev = self._debounce
		if not newbounce:
			self._debounce = True
			while self._taskno < len(self._scheduler):
				task = self._scheduler[self._taskno]
				task[0](*task[1])
				self._taskno+=1
			self._scheduler = []
			self._taskno = 0
		self._debounce = newbounce
		return prev

class Main:
	'''Main class; handles all IO and defers to overlays'''
	last = 0
	def __init__(self,two56colors,loop=None):
		self.loop = asyncio.get_event_loop() if loop is None else loop
		self._screen = curses.initscr()		#init screen
		#sadly, I can't put this in main.loop to make it more readable
		curses.noecho(); curses.cbreak(); self._screen.keypad(1) #setup curses
		self._screen.nodelay(1)	#don't wait for enter to get input
		#scheduler 
		self._schedule = _Schedule()
		self.active = True
		self.candisplay = True
		#guessed terminal dimensions
		self.x = 40
		self.y = 70
		#256 mode
		if two56colors:
			#the start of 256 color definitions
			self._two56 = True
			self.two56start = len(_COLORS) + rawNum(0)
			def256colors()
		else:
			self._two56 = False
		self.two56 = property(lambda: self._two56)
		#input/display stack
		self._ins = []
		self._scrolls = []
		#last high-priority overlay
		self._lastReplace = 0
		self._blurbQueue = []
		self._bottom_edges = [" "," "]
	#Display Backends----------------------------------------------------------
	@asyncio.coroutine
	def display(self):
		'''Display backend'''
		if not self.active: return
		if not self.candisplay: return
		#justify number of lines
		lines = ["" for i in range(self.y)]
		#start with the last "replacing" overlay, then draw all overlays afterward
		try:
			for start in range(self._lastReplace,len(self._ins)):
				yield from self._ins[start](lines)
		except SizeException:
			self.candisplay = 0
			return
		#main display method: move to top of screen
		_moveCursor()
		print("\x1b[?25l",end="")
		#draw each line in lines, deleting the rest of the garbage on the line
		for i in lines:
			print(i,end="\x1b[K\n\r") 
		print(CHAR_RETURN_CURSOR,end="")
	@asyncio.coroutine
	def updateinput(self):
		'''Input display backend'''
		if not (self.active and self.candisplay): return
		if not self._scrolls: return	#no textoverlays added, but how are you firing this
		string = format(self._scrolls[-1])
		_moveCursor(self.y+1)
		print("%s\x1b[K" % string,end=CHAR_RETURN_CURSOR)
	@asyncio.coroutine
	def _printblurb(self,blurb,time):
		'''Blurb display backend'''
		if not (self.active and self.candisplay): return
		if self.last < 0: return
		#try to queue a blurb	
		if blurb == "": pass
		elif isinstance(blurb,Coloring):
			vector,_ = blurb.breaklines(self.x)
			self._blurbQueue = vector
		else:
			vector,_ = Coloring(blurb).breaklines(self.x)
			self._blurbQueue = vector
		#next blurb is either a pop from the last message or nothing
		if len(self._blurbQueue):
			blurb = self._blurbQueue.pop(0)
		else:
			blurb = ""
		self.last = time
		_moveCursor(self.y+2)
		print("{}\x1b[K".format(blurb),end=CHAR_RETURN_CURSOR)

	@asyncio.coroutine
	def _updateinfo(self,right,left):
		'''Info window backend'''
		if not (self.active and self.candisplay): return
		_moveCursor(self.y+3)
		self._bottom_edges[0] = left or self._bottom_edges[0]
		self._bottom_edges[1] = right or self._bottom_edges[1]
		room = self.x - collen(self._bottom_edges[0]) - collen(self._bottom_edges[1])
		if room < 1: return
		#selected, then turn off
		print("\x1b[7m{}{}{}\x1b[0m".format(self._bottom_edges[0],
			" "*room,self._bottom_edges[1]),end=CHAR_RETURN_CURSOR)
	#Display Frontends----------------------------------------------------------
	def newBlurb(self,message = ""):
		'''Add blurb. Use in conjunction with MainOverlay to erase'''
		self.loop.create_task(self._printblurb(message,time.time()))
	def holdBlurb(self,message):
		'''Hold blurb. Sets self.last to -1, making newBlurb not draw'''
		self.loop.create_task(self._printblurb(message,-1))
	def releaseBlurb(self):
		'''
		Release blurb. Sets self.last to a valid time, making newBlurb
		start drawing again.
		'''
		self.loop.create_task(self._printblurb(message,"",time.time()))
	def updateinfo(self,right = None,left = None):
		'''Update screen bottom'''
		self.loop.create_task(self._updateinfo(right,left))
	#Overlay Frontends---------------------------------------------------------
	@asyncio.coroutine
	def addOverlay(self,new):
		'''Add overlay'''
		if not isinstance(new,OverlayBase): return
		new.index = len(self._ins)
		self._ins.append(new)
		if new.replace: self._lastReplace = new.index
		#display is not strictly called beforehand, so better safe than sorry
		yield from self.display()
	@asyncio.coroutine
	def popOverlay(self,overlay):
		'''Pop the overlay `overlay`'''
		del self._ins[overlay.index]
		#look for the last replace
		if overlay.index == self._lastReplace: 
			newReplace = 0
			for start in range(len(self._ins)):
				if self._ins[-start-1].replace:
					newReplace = start
					break
			self._lastReplace = newReplace
		yield from self.display()
	def getOverlay(self,index):
		'''
		Get an overlay by its index in self._ins. Returns None
		if index is invalid
		'''
		if len(self._ins) and index < len(self._ins):
			return self._ins[index]
		return None
	def getOverlaysByClassName(self,name,highest=0):
		'''
		Like getElementsByClassName in a browser.
		Returns a list of Overlays with the class name `name`
		'''
		#use string __name__s in case scripts can't get access to the method
		if type(name) == type:
			name = name.__name__
		#limit the highest index
		if not highest:
			highest = len(self._ins)

		ret = []
		for i in range(highest):
			overlay = self._ins[i]
			#respect inheritence
			if name in [j.__name__ for j in type(overlay).mro()]:
				ret.append(overlay)
		return ret
	def addScrollable(self):
		'''Add a new scrollable and return it'''
		newScroll = _NScrollable(self.x,self,len(self._scrolls))
		self._scrolls.append(newScroll)
		self.loop.create_task(self.updateinput())
		return newScroll
	def popScrollable(self,which):
		'''Pop a scrollable added from addScrollable'''
		del self._scrolls[which.index]
		self.loop.create_task(self.updateinput())
	#Loop Backend--------------------------------------------------------------
	@asyncio.coroutine
	def _input(self):
		'''Crux of input. Submain client loop'''
		chars = []
		try:
			next = -1
			while next == -1:
				next = self._screen.getch()
				yield from asyncio.sleep(.01) #less CPU intensive
			chars.append(next)
			while next != -1:
				next = self._screen.getch()
				chars.append(next)
		except KeyboardInterrupt:
			self.active = False
			return
		except ControlZ:
			chars.append('\26')
		if not len(self._ins): return
		return self._ins[-1].runkey(chars)
	@asyncio.coroutine
	def loop(self):
		'''Main client loop'''
		try:
			while self.active:
				inp = yield from self._input()
				if inp:
					if inp == -1:
						self._ins[-1].remove()
					yield from self.display()
		finally:
			#return the terminal sane mode. undo what's in init
			curses.echo(); curses.nocbreak(); self._screen.keypad(0)
			curses.endwin()
			self.active = False
			#let overlays do cleanup
			for i in self._ins:
				try:
					i.remove()
				except: pass
	#Frontends------------------------------------------------------------------
	@asyncio.coroutine
	def resize(self):
		'''Resize the GUI'''
		newy, newx = self._screen.getmaxyx()
		newy -= RESERVE_LINES
		try:
			for i in self._ins:
				yield from i.resize(newx,newy)
		except SizeException:
			self.x,self.y = newx,newy
			self.candisplay = 0
			return
		self.x,self.y = newx,newy
		self.candisplay = 1
		self.updateinfo()
		yield from self.updateinput()
		yield from self.display()
	def toggle256(self,value):
		'''Turn the mode to 256 colors, and if undefined, define colors'''
		self._two56 = value
		if value and not hasattr(self,"two56start"): #not defined on startup
			self.two56start = len(_COLORS) + rawNum(0)
			def256colors()
	def toggleMouse(self,state):
		'''Turn the mouse on or off'''
		return curses.mousemask(state and _MOUSE_MASK)
	def catcherr(self,func,*args):
		'''Catch error and end client'''
		def wrap():
			global lasterr
			try:
				func(*args)
			except Exception as e:
				lasterr = e
				self.active = False
				curses.ungetch('\x1b')
		return wrap

#TODO work on how to start the Main instance
def start(target,*args,two56=False):
	'''Start the client. Run this!'''
	if not (sys.stdin.isatty() and sys.stdout.isatty()): #check if terminal
		raise IOError("This script is not intended to be piped")
	main_instance = Main(two56)
	main_instance.resize()
	#daemonize functions bot_thread
#	bot_thread = Thread(target=main_instance.catcherr(target,main_instance,*args))
#	bot_thread.daemon = True
#	bot_thread.start()
	
	main_instance.loop()	#main program loop
	try:
		for i,j in _afterDone:
			i(*j)
	except Exception as e:
		raise Exception("Error occurred during shutdown") from e
	if lasterr is not None:
		raise lasterr

#display list of defined commands
@command("help")
def listcommands(parent,*args):
	def select(self):
		new = CommandOverlay(parent,self.caller)
		new.text.append(self.list[self.it])
		self.swap(new)

	commandsList = ListOverlay(parent,list(_commands))
	commandsList.addKeys({
		"enter":select
	})
	return commandsList

@command("q")
def quit(parent,*args):
	parent.active = False
