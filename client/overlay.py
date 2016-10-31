#!/usr/bin/env python3
#client.overlay.py
'''
Client module with single-byte curses input uses a
system of overlays, pulling input from the topmost
one. Output is done not with curses display, but various
different stdout printing calls.
'''
#TODO	dbmsg that turns off cbreak mode and back on
#TODO	overlay-specific lookup tables
try:
	import curses
except ImportError:
	raise ImportError("ERROR WHILE IMPORTING CURSES, is this running on Windows cmd?")
import sys
from os import environ
if not (sys.stdin.isatty() and sys.stdout.isatty()): #check if terminal
	raise IOError("This script is not intended to be piped")
#escape has delay typically
environ.setdefault("ESCDELAY", "25")
import time
from threading import Thread
from .display import *

__all__ =	["CHAR_COMMAND","start","soundBell","Box","filter","colorize"
			,"command","OverlayBase","TextOverlay","ListOverlay","ColorOverlay"
			,"InputOverlay","ConfirmOverlay","MainOverlay"
			,"onTrueFireMessage","onDone"]

main_instance = None
lasterr = None
#break if smaller than these
RESERVE_LINES = 3
_MIN_X = 0
_MIN_Y = 0
def setmins(newx,newy):
	'''Set minimum width/height'''
	global _MIN_X,_MIN_Y
	_MIN_X=max(_MIN_X,newx)
	_MIN_Y=max(_MIN_Y,newy)

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
		if name not in _VALID_KEYNAMES: #don't map KEY_BACKSPACE or KEY_ENTER
			_VALID_KEYNAMES[name] = getattr(curses,i)
#simplicity's sake
for i in range(32):
	#no, not +96 because that gives wrong characters for ^@ and ^_ (\x00 and \x1f)
	_VALID_KEYNAMES["^%s"%chr(i+64).lower()] = i
for i in range(32,256):
	_VALID_KEYNAMES[chr(i)] = i
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
_colorizers = []
_filters = []
_commands = {}
_afterDone = []

#decorators for containers
def colorize(func):
	'''Add function as a colorizer'''
	_colorizers.append(func)
def filter(func):
	'''Add function as a filter'''
	_filters.append(func)
def command(commandname):
	'''Add function as a command `commandname`'''
	def wrapper(func):
		_commands[commandname] = func
	return wrapper
def onDone(func):
	_afterDone.append(func)
	return func

#OVERLAY HELPERS------------------------------------------------------------------
CHAR_COMMAND = "`"
Tabber(CHAR_COMMAND,_commands)

def centered(string,width):
	'''Center some text'''
	return string.rjust((width+len(string))//2).ljust(width)

class Box:
	'''
	Group of useful box shaping characters. To use, inherit from
	OverlayBase and this class simultaneously.
	'''
	parent = None
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
		return "{}{}".format(string,justchar*(self.parent.x-2-strlen(string)))
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

class History:
	'''Container class for historical entries, similar to an actual shell'''
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

def _moveCursor(row = 0):
	'''Move the cursor to the row number specified'''
	print("\x1b[%d;f" % row,end=CLEAR_FORMATTING)
def soundBell():
	'''Sound console bell. Just runs `print("\a",end="")`'''
	print("\a",end="")

#please don't need these
quitlambda = lambda x: -1
def staticize(func,*args):
	'''Staticizes a function and its arguments into a function with one argument.'''
	def ret(garbage):			#garbage would be a list of characters
		return func(*args)
	ret.__doc__ = func.__doc__	#preserve documentation text
	return ret

class OverlayBase:
	'''
	Virtual class that redirects input to callbacks and modifies a list
	of (output) strings. All overlays must descend from OverlayBase
	'''
	def __init__(self,parent):
		self.parent = parent		#parent
		self.index = None			#index in the stack
		self._keys = {
			27:	self._callalt
			,curses.KEY_RESIZE:	lambda x: parent.resize() or 1
		}
		self._altkeys =	{None: lambda: -1}
	def __dir__(self):
		'''Get a list of keynames and their documentation'''
		ret = []
		for i,j in _VALID_KEYNAMES.items():
			#ignore named characters and escape, they're not verbose
			if i in ("^[","^i","^j",chr(127)): continue	
			if j in self._keys:
				ret.append("{}: {}".format(i,self._keys[j].__doc__))
			if j in self._altkeys:
				ret.append("a-{}: {}".format(i,self._altkeys[j].__doc__))
		ret.sort()
		return ret
	def __call__(self,lines):
		'''
		Overridable function. Modify lines by address (i.e lines[value])
		to display from main
		'''
		pass
	def _callalt(self,chars):
		'''Run a alt-key's callback'''
		return chars[0] in self._altkeys and self._altkeys[chars[0]]()
	def _post(self):
		'''
		Run after a keypress if the associated function returns boolean false
		If either the keypress or this return boolean true, the overlay's
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
		if char in self._keys:	#ignore the command character and trailing -1
			return self._keys[char](chars[1:-1] or [None]) or self._post()
		elif char in range(32,255) and -1 in self._keys:	#ignore the trailing -1
			return self._keys[-1](chars[:-1]) or self._post()
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
				else:
					try:
						i = _VALID_KEYNAMES[i]
					except: raise KeyException("key {} not defined".format(i))
			if areMethods:
				self._keys[i] = staticize(j)
			else:
				self._keys[i] = staticize(j,self)

class TextOverlay(OverlayBase):
	'''Virtual overlay with text input (at bottom of screen)'''
	def __init__(self,parent = None):
		OverlayBase.__init__(self,parent)
		self.text = parent.addScrollable()
		self._keys.update({
			-1:				self._input
			,9:				staticize(self.text.complete)
			,127:			staticize(self.text.backspace)
			,curses.KEY_DC:		staticize(self.text.delchar)
			,curses.KEY_SHOME:	staticize(self.text.clear)
			,curses.KEY_RIGHT:	staticize(self.text.movepos,1)
			,curses.KEY_LEFT:	staticize(self.text.movepos,-1)
			,curses.KEY_HOME:	staticize(self.text.home)
			,curses.KEY_END:	staticize(self.text.end)
		})
		self._altkeys.update({
			127:			self.text.delword
		})
	def _input(self,chars):
		'''Safe appending to scrollable. Takes out invalid ASCII (chars above 256) that might get pushed by curses'''
		return self.text.append(bytes([i for i in chars if i<256]).decode())
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
		nexthist = lambda x: scroll.setstr(history.nexthist())
		prevhist = lambda x: scroll.setstr(history.prevhist())
		#preserve docstrings for getKeynames
		nexthist.__doc__ = history.nexthist.__doc__
		prevhist.__doc__ = history.prevhist.__doc__
		self._keys.update({
			curses.KEY_UP:		nexthist
			,curses.KEY_DOWN:	prevhist
		})

class ListOverlay(OverlayBase,Box):
	'''Display a list of objects, optionally drawing something additional'''
	replace = True
	#worst case column: |(value[0])...(value[1])|
	#				    1    2     345  6	    7
	#worst case rows: |(list member)|(RESERVED)
	#				  1	2			3
	setmins(7,3)
	def __init__(self,parent,outList,drawOther = None,modes = [""]):
		OverlayBase.__init__(self,parent)
		self.it = 0
		self.mode = 0
		self.list = outList
		self._drawOther = drawOther
		self._modes = modes
		self._nummodes = len(modes)
		self._numentries = len(self.list)
		self._keys.update({
			ord('j'):	staticize(self.increment,1) #V I M
			,ord('k'):	staticize(self.increment,-1)
			,ord('l'):	staticize(self.chmode,1)
			,ord('h'):	staticize(self.chmode,-1)
			,ord('q'):	quitlambda
			,curses.KEY_DOWN:	staticize(self.increment,1)
			,curses.KEY_UP:		staticize(self.increment,-1)
			,curses.KEY_RIGHT:	staticize(self.chmode,1)
			,curses.KEY_LEFT:	staticize(self.chmode,-1)
		})
	def __call__(self,lines):
		'''
		Display a list in a box. If too long, entries are trimmed
		to include an ellipsis
		'''
		lines[0] = self.box_top()
		size = self.parent.y-2
		maxx = self.parent.x-2
		#which portion of the list is currently displaced
		partition = (self.it//size)*size
		#get the partition of the list we're at, pad the list
		subList = self.list[partition:partition+size]
		subList = subList + ["" for i in range(size-len(subList))]
		#display lines
		for i,value in enumerate(subList):
			half = maxx//2
			#add an elipsis in the middle of the string if it can't be displayed; also, right justify
			row = (len(value) > maxx) and value[:max(half,1)] + "..." + value[min(-half+3,-1):] or value
			row = Coloring(self.box_just(row))
			if value and self._drawOther is not None:
				self._drawOther(row,i+partition)
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

class ColorOverlay(OverlayBase,Box):
	'''Display 3 bars for red, green, and blue. Allows exporting of color as hex'''
	replace = True
	NAMES = ["Red","Green","Blue"]
	#worst case column: |Red  GreenBlue |
	#		  			123456789ABCDEFGH = 17
	#worst case rows: |(color row) (name)(val) (hex)|(RESERVED)
	#		  1	2     3	 4	5 6  7  8
	setmins(17,8)
	def __init__(self,parent,initcolor = [127,127,127]):
		OverlayBase.__init__(self,parent)
		#allow setting from hex value
		if isinstance(initcolor,str):
			self.setHex(initcolor)
		else:
			self.color = initcolor
		self._rgb = 0
		self._keys.update({
			ord('q'):		quitlambda
			,ord('k'):		staticize(self.increment,1)
			,ord('j'):		staticize(self.increment,-1)
			,ord('l'):	staticize(self.chmode,1)
			,ord('h'):	staticize(self.chmode,-1)
			,curses.KEY_UP:		staticize(self.increment,1)
			,curses.KEY_DOWN:	staticize(self.increment,-1)
			,curses.KEY_PPAGE:	staticize(self.increment,10)
			,curses.KEY_NPAGE:	staticize(self.increment,-10)
			,curses.KEY_HOME:	staticize(self.increment,255)
			,curses.KEY_END:	staticize(self.increment,-255)
			,curses.KEY_RIGHT:	staticize(self.chmode,1)
			,curses.KEY_LEFT:	staticize(self.chmode,-1)
		})
	def __call__(self,lines):
		'''Display 3 bars, their names, values, and string in hex'''
		wide = (self.parent.x-2)//3 - 1
		space = self.parent.y-7
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
		TextOverlay.__init__(self,parent)
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
	def __init__(self,parent = None):
		TextOverlay.__init__(self,parent)
		self.text.setnonscroll(CHAR_COMMAND)
		self.controlHistory(self.history,self.text)
		self._keys.update({
			10:		staticize(self._run)
			,127:	staticize(self._backspacewrap)
		})
		self._altkeys.update({
			127:	lambda: -1
		})
	def __call__(self,lines):
		lines[-1] = "COMMAND"
	def _backspacewrap(self):
		'''Backspace a char, or quit out if there are no chars left'''
		if not str(self.text): return -1
		self.text.backspace()
	def _run(self):
		'''Run command'''
		text = str(self.text)
		self.history.append(text)
		arglist = text.split(' ')
		if arglist[0] not in _commands:
			self.parent.newBlurb("Command \"{}\" not found".format(arglist[0]))
			return -1
		command = _commands[arglist[0]]
		try:
			add = command(self.parent,*arglist[1:])
			if isinstance(add,OverlayBase):
				self.swap(add)
				return
		except Exception as exc:
			dbmsg('{} occurred in command {}: {}'.format(
				type(exc).__name__,arglist[0], exc))
		except KeyboardInterrupt: pass
		return -1

class EscapeOverlay(OverlayBase):
	'''Overlay for redirecting input after \ is pressed'''
	replace = False
	def __init__(self,parent,scroll):
		OverlayBase.__init__(self,parent)
		self._keys.update({
			-1:		quitlambda
			,10:		quitlambda
			,ord('n'):	lambda x: scroll.append('\n') or -1
			,ord('\\'):	lambda x: scroll.append('\\') or -1
			,ord('t'):	lambda x: scroll.append('\t') or -1
		})

class ConfirmOverlay(OverlayBase):
	'''Overlay to confirm selection confirm y/n (no slash)'''
	replace = False
	def __init__(self,parent,prompt,confirmfunc):
		OverlayBase.__init__(self,parent)
		self.parent.holdBlurb(prompt)
		self._keys.update({ #run these in order
			ord('y'):	lambda x: confirmfunc() or self.parent.releaseBlurb() or -1
			,ord('n'):	lambda x: self.parent.releaseBlurb() or -1
		})

class MainOverlay(TextOverlay):
	'''
	Overlay that can push and select messages, and has an input box.
	Optionally pushes time messages every 10 minutes and refreshes 
	blurbs every few seconds
	'''
	replace = True
	#sequence between messages to draw reversed
	INDENT = "    "
	_msgSplit = '\x1b' 
	def __init__(self,parent,pushtimes = True):
		TextOverlay.__init__(self,parent)
		self._pushtimes = pushtimes
		self.history = History()
		self.clear()
		self.controlHistory(self.history,self.text)
		self._keys.update({
			ord('\\'):		staticize(self._replaceback)
		})
		self._altkeys.update({
			ord('k'):		self.selectup		#muh vim t. me
			,ord('j'):		self.selectdown
		})
	def __call__(self,lines):
		'''Display messages'''
		select = SELECT_AND_MOVE
		#seperate traversals
		selftraverse,linetraverse = -1,-2
		lenself, lenlines = len(self._lines),len(lines)
		msgno = 0
		#go backwards by default
		direction = -1
		if self._linesup-self._unfiltup >= lenlines:
			direction = 1
			msgno = self._unfiltup
			selftraverse,linetraverse = -self._linesup,-lenlines
			lenself, lenlines = -1,-2
		#traverse list of lines
		while (selftraverse*direction) <= lenself and \
		(linetraverse*direction) <= lenlines:
			if self._lines[selftraverse] == self._msgSplit:
				selftraverse += direction #disregard this line
				msgno -= direction #count lines down downward, up upward
				continue
			reverse = (msgno == self._unfiltup) and select or ""
			lines[linetraverse] = reverse + self._lines[selftraverse]
			selftraverse += direction
			linetraverse += direction
		lines[-1] = Box.CHAR_HSPACE*self.parent.x
	#method overloading---------------------------------------------------------
	def _input(self,chars):
		'''Input some text, or enter CommandOverlay'''
		if not str(self.text) and len(chars) == 1 and \
		chars[0] == ord(CHAR_COMMAND):
			CommandOverlay(self.parent).add()
			return
		#allow unicode input
		return TextOverlay._input(self,chars)
	def _post(self):
		'''Stop selecting'''
		if self._selector:
			self._selector = 0
			self._linesup = 0
			self._unfiltup = 0
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
	def resize(self,newx,newy):
		'''Resize scrollable and maybe draw lines again if width changed'''
		super().resize(newx,newy)
		if newx != self.parent.x:
			self.redolines(newx,newy)
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
		'''
		Add a newline if the next character is n, or a tab
		if the next character is t
		'''
		EscapeOverlay(self.parent,self.text).add()
	#MESSAGE SELECTION----------------------------------------------------------
	def _getnextmessage(self,step):
		'''Backend for selecting message'''
		select = self._selector+step
		addlines = 0
		while not addlines and select <= len(self._allMessages):
			addlines = self._allMessages[-select][2]
			select += step
		#if we're even "going" anywhere
		if select-step-self._selector:
			self._selector = max(0,select-step)
			self._unfiltup = max(0,self._unfiltup+step)
		return addlines
	def _maxselect(self):
		soundBell()
	def selectup(self):
		'''Select message up'''
		#go up the number of lines of the "next" selected message
		upmsg = self._getnextmessage(1)
		#but only if there is a next message
		if not upmsg: self._maxselect()
		else:
			self._linesup += upmsg+1
			if self._linesup > len(self._lines):	#don't forget the new lines
				cur = self.getselected()
				a,b = cur[0].breaklines(self.parent.x,self.INDENT)
				a.append(self._msgSplit)
				self._lines = a + self._lines
				cur[2] = b
		return 1
	def selectdown(self):
		'''Select message down'''
		#go down the number of lines of the currently selected message
		self._linesup = max(0,self._linesup-self.getselected()[2]-1)
		self._getnextmessage(-1)
		if not self._selector:
			self.parent.updateinput()	#move the cursor back
		return 1
	#FRONTENDS--------------------------------------------------
	def isselecting(self):
		'''Whether a message is selected or not'''
		return bool(self._selector)
	def getselected(self):
		'''
		Frontend for getting the selected message. Returns a tuple of
		length three: the message (in a coloring object), an argument tuple,
		and how many lines it occupies
		'''
		return self._allMessages[-self._selector]
	def redolines(self,width = None,height = None):
		'''
		Redo lines, if current lines does not represent the unfiltered messages
		or if the width has changed
		'''
		if width is None: width = self.parent.x
		if height is None: height = self.parent.y
		newlines = []
		numup,nummsg = 0,1
		#while there are still messages to add (to the current height)
		while numup < height and nummsg <= len(self._allMessages):
			i = self._allMessages[-nummsg]
			#if a filter fails, then the message should be drawn, as it's likely a system message
			try:
				if any(j(*i[1]) for j in _filters):
					i[2] = 0
					nummsg += 1
					continue
			except: pass
			a,b = i[0].breaklines(width,self.INDENT)
			a.append(self._msgSplit)
			newlines = a + newlines
			i[2] = b
			numup += b
			nummsg += 1
		self._lines = newlines
	def recolorlines(self):
		'''
		Re-apply colorizers and redraw all visible lines
		'''
		width = self.parent.x
		height = self.parent.y
		newlines = []
		numup,nummsg = 0,1
		while (numup < height or nummsg <= self._selector) and nummsg <= len(self._allMessages):
			i = self._allMessages[-nummsg]
			if not i[3]:	#don't decolor system messages
				i[0].clear()
				for j in _colorizers:
					j(i[0],*i[1])
			try:
				if any(j(*i[1]) for j in _filters):
					i[2] = 0
					nummsg += 1
					continue
			except: pass
			a,b = i[0].breaklines(width,self.INDENT)
			a.append(self._msgSplit)
			newlines = a + newlines
			i[2] = b
			numup += b
			nummsg += 1
		self._lines = newlines
		self.parent.display()

	def clear(self):
		'''Clear all lines and messages'''
		#these two REALLY should be private
		self._allMessages = []
		self._lines = []
		#these too because they select the previous two
		self._selector = 0
		self._unfiltup = 0
		self._linesup = 0
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
		'''Parse a message and apply all colorizers'''
		post = Coloring(post)
		for i in _colorizers:
			i(post,*args)
		self._append(post,list(args))
		self.parent.display()
	#MESSAGE PUSHING BACKEND-----------------------------------
	def _append(self,newline,args = None,isSystem = False):
		'''Add new message. Use msgPost instead'''
		#undisplayed messages have length zero
		msg = [newline,args,0,isSystem]
		self._selector += (self._selector>0)
		#run filters
		try:
			if any(i(*args) for i in _filters):
				self._allMessages.append(msg)
				return
		except: pass
		a,b = newline.breaklines(self.parent.x,self.INDENT)
		self._lines += a
		msg[2] = b
		self._allMessages.append(msg)
		self._lines.append(self._msgSplit)
		#keep the right message selected
		if self._selector:
			self._linesup += b+1
			self._unfiltup += 1

class _NScrollable(Scrollable):
	'''
	A scrollable that expects a Main object as parent so that it 
	can run Main.updateinput()
	'''
	def __init__(self,width,parent,index):
		Scrollable.__init__(self,width)
		self.parent = parent
		self.index = index
	def _onchanged(self):
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
	def __init__(self):
		self._screen = curses.initscr()		#init screen
		#sadly, I can't put this in main.loop to make it more readable
		curses.noecho(); curses.cbreak(); self._screen.keypad(1) #setup curses
		self._screen.nodelay(1)	#don't wait for enter to get input

		self._schedule = _Schedule()
		self.active = True
		self.candisplay = True
		#guessed terminal dimensions
		self.x = 40
		self.y = 70
		#input/display stack
		self._ins = []
		self._scrolls = []
		self._lastReplace = 0
		self._blurbQueue = []
		self._bottom_edges = [" "," "]
	#Display Backends----------------------------------------------------------
	def _display(self):
		'''Display backend'''
		if not self.active: return
		if not self.candisplay: return
		#justify number of lines
		lines = ["" for i in range(self.y)]
		#start with the last "replacing" overlay, then draw all overlays afterward
		for start in range(self._lastReplace,len(self._ins)):
			self._ins[start](lines)
		#main display method: move to top of screen
		_moveCursor()
		curses.curs_set(0)
		#draw each line in lines, deleting the rest of the garbage on the line
		for i in lines:
			print(i,end="\x1b[K\n\r") 
		curses.curs_set(1)
		print(CHAR_RETURN_CURSOR,end="")
	def _updateinput(self):
		'''Input display backend'''
		if not (self.active and self.candisplay): return
		if not self._scrolls: return	#no textoverlays added, but how are you firing this
		string = format(self._scrolls[-1])
		_moveCursor(self.y+1)
		print("{}\x1b[K".format(string),end=CHAR_RETURN_CURSOR)
	def _printblurb(self,blurb,time):
		'''Blurb display backend'''
		if not (self.active and self.candisplay): return
		if self.last < 0: return

		if blurb == "":
			pass
		elif isinstance(blurb,Coloring):
			vector,_ = blurb.breaklines(self.x)
			self._blurbQueue.extend(vector)
		else:
			vector,_ = Coloring(blurb).breaklines(self.x)
			self._blurbQueue.extend(vector)
			
		if len(self._blurbQueue):
			blurb = self._blurbQueue.pop(0)
		else:
			blurb = ""

		self.last = time
		_moveCursor(self.y+2)
		print("{}\x1b[K".format(blurb),end=CHAR_RETURN_CURSOR)
	def _releaseblurb(self):
		'''Release blurb backend'''
		self.last = time.time()
	def _updateinfo(self,right,left):
		'''Info window backend'''
		if not (self.active and self.candisplay): return
		_moveCursor(self.y+3)
		self._bottom_edges[0] = left or self._bottom_edges[0]
		self._bottom_edges[1] = right or self._bottom_edges[1]
		room = self.x - strlen(self._bottom_edges[0]) - strlen(self._bottom_edges[1])
		if room < 1: return
		#selected, then turn off
		print("\x1b[7m{}{}{}\x1b[0m".format(self._bottom_edges[0],
			" "*room,self._bottom_edges[1]),end=CHAR_RETURN_CURSOR)
	#Display Frontends----------------------------------------------------------
	def display(self):
		self._schedule(self._display)
	def updateinput(self):
		'''Update input'''
		self._schedule(self._updateinput)
	def newBlurb(self,message = ""):
		'''Add blurb. Use in conjunction with MainOverlay to erase'''
		self._schedule(self._printblurb	,message,time.time())
	def holdBlurb(self,string):
		'''Hold blurb. Sets self.last to -1, making newBlurb not draw'''
		self._schedule(self._printblurb	,string	,-1)
	def releaseBlurb(self):
		'''
		Release blurb. Sets self.last to a valid time, making newBlurb
		start drawing again.
		'''
		self._schedule(self._releaseblurb)
		self._schedule(self._printblurb,"",time.time())
	def updateinfo(self,right = None,left = None):
		'''Update screen bottom'''
		self._schedule(self._updateinfo,right,left)
	#Overlay Frontends---------------------------------------------------------
	def addOverlay(self,new):
		'''Add overlay'''
		if not isinstance(new,OverlayBase): return
		new.index = len(self._ins)
		self._ins.append(new)
		if new.replace: self._lastReplace = new.index
		#display is not strictly called beforehand, so better safe than sorry
		self.display()
	def popOverlay(self,overlay):
		'''Pop the overlay `overlay`'''
		self._ins.pop(overlay.index)
		#look for the last replace
		if overlay.index == self._lastReplace: 
			newReplace = 0
			for start in range(len(self._ins)):
				if self._ins[-start-1].replace:
					newReplace = start
					break
			self._lastReplace = newReplace
		self.display()
	def getOverlay(self,index):
		'''
		Get an overlay by its index in self._ins. Returns None
		if index is invalid
		'''
		if len(self._ins) and index < len(self._ins):
			return self._ins[index]
		return None
	def getOverlaysByClassName(self,name):
		'''
		Like getElementByClassName in a browser.
		Returns a list of Overlays with the class name `name`
		'''
		ret = []
		for i in self._ins:
			if type(i).__name__ == name:
				ret.append(i)
		return ret
	def addScrollable(self):
		'''Add a new scrollable and return it'''
		newScroll = _NScrollable(self.x,self,len(self._scrolls))
		self._scrolls.append(newScroll)
		self.updateinput()
		return newScroll
	def popScrollable(self,which):
		'''Pop a scrollable added from addScrollable'''
		self._scrolls.pop(which.index)
		self.updateinput()
	#Loop Backend--------------------------------------------------------------
	def _input(self):
		'''Crux of input. Submain client loop'''
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
			self.active = False
			return
		if not len(self._ins): return
		return self._ins[-1].runkey(chars)
	def loop(self):
		'''Main client loop'''
		try:
			while self.active:
				inp = self._input()
				if inp:
					if inp == -1:
						self._ins[-1].remove()
					self.display()
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
	def resize(self):
		'''Resize the GUI'''
		newy, newx = self._screen.getmaxyx()
		newy -= RESERVE_LINES
		try:
			if newy < _MIN_Y or newx < _MIN_X:
				raise SizeException()
			for i in self._ins:
				i.resize(newx,newy)
		except SizeException:
			self.x,self.y = newx,newy
			self.candisplay = 0
			return
		self.x,self.y = newx,newy
		self.candisplay = 1
		self.updateinput()
		self.updateinfo()
		self.display()
	def catcherr(self,func,*args):
		'''Catch error and end client'''
		def wrap():
			try:
				func(*args)
			except Exception as e:
				dbmsg("ERROR OCCURRED, ABORTING")
				global lasterr
				lasterr = e
				self.active = False
				curses.ungetch('\x1b')
		return wrap

def start(target,*args):
	'''Start the client. Run this!'''
	global main_instance
	main_instance = Main()
	main_instance.resize()
	#daemonize functions bot_thread
	bot_thread = Thread(target=main_instance.catcherr(target,main_instance,*args))
	bot_thread.daemon = True
	bot_thread.start()
	main_instance.loop()	#main program loop
	for i in _afterDone:
		i()
	if lasterr:
		raise lasterr

class onTrueFireMessage:
	def __init__(self,message):
		self.message = message
	def __call__(self,other):
		def inject(*args):
			if main_instance:
				if other(*args):
					main_instance.newBlurb(self.message)
		return inject

#display list of defined commands
@command("help")
def listcommands(parent,*args):
	def select(self):
		new = CommandOverlay(parent)
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
