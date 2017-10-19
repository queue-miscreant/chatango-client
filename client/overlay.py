#!/usr/bin/env python3
#client.overlay.py
'''
Client module with single-byte curses input uses a
system of overlays, pulling input from the topmost
one. Output is not done with curses display, but various
different stdout printing calls.
'''
#TODO	canscroll really means cangetmore, and locks when at the top and no more messages are retrieved

try:
	import curses
except ImportError:
	raise ImportError("Could not import curses; is this running on Windows cmd?")

import sys
import os
import asyncio
import traceback
from signal import SIGTSTP,SIGINT #redirect ctrl-z and ctrl-c
from functools import partial
from time import time,localtime,strftime as format_time
from .display import *

__all__ =	["CHAR_COMMAND","soundBell","Box","command"
			,"OverlayBase","TextOverlay","ListOverlay","ColorOverlay"
			,"ColorSliderOverlay","InputOverlay","ConfirmOverlay"
			,"BlockingOverlay","MainOverlay","DisplayOverlay","onDone"
			,"override","staticize","Main"]

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
	,curses.KEY_ENTER:		10
	#ctrl-m to ctrl-j (carriage return to line feed)
	#this really shouldn't be necessary, since curses does that
	,13:					10
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
#getch tends to hang on nodelay if PRESSED buttons are part of the mask,
#but RELEASED aren't; wheel up/down doesn't count
_MOUSE_BUTTONS = {
	"left":			curses.BUTTON1_CLICKED
	,"middle":		curses.BUTTON2_CLICKED
	,"right":		curses.BUTTON3_CLICKED
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
	if asyncio.iscoroutinefunction(func):
		raise Exception("Please pass a coroutine, not a generator into onDone")
	elif not asyncio.iscoroutine(func):
		func = asyncio.coroutine(func)(*args)
	_afterDone.append(func)
	return func

#OVERLAY HELPERS------------------------------------------------------------------
CHAR_COMMAND = '`'

class History:
	'''Container class for historical entries, similar to an actual shell'''
	def __init__(self):
		self.history = []
		self._selhis = 0
		#storage for next entry, so that you can scroll up, then down again
		self.bottom = None

	def nexthist(self,replace=""):
		'''Next historical entry (less recent)'''
		if self.history:
			if replace:
				if not self._selhis:
					#at the bottom, starting history
					self.bottom = replace
				else:
					#else, update the entry
					self.history[-self._selhis] = replace
			#go backward in history
			self._selhis += (self._selhis < (len(self.history)))
			#return what we just retrieved
			return self.history[-self._selhis]
		return ""

	def prevhist(self,replace=""):
		'''Previous historical entry (more recent)'''
		if self.history:
			if replace and self._selhis: #not at the bottom already
				self.history[-self._selhis] = replace
			#go forward in history
			self._selhis -= (self._selhis > 0)
			#return what we just retreived
			return (self._selhis and self.history[-self._selhis]) or self.bottom or ""
		return ""

	def append(self,new):
		'''Add new entry in history and maintain a size of at most 50'''
		if not self.bottom:
			#not already added from history manipulation
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
	print(end="\a")

quitlambda = lambda x: -1
quitlambda.__doc__ = "Close current overlay"
def staticize(func,*args,doc=None,**kwargs):
	'''functools.partial but conserves or adds documentation'''
	ret = partial(func,*args,**kwargs)
	ret.__doc__ = doc or func.__doc__ or "(no documentation)"
	return ret

class override:
	'''Create a new function that returns `ret`. Avoids (or ensures) '''+\
	'''firing _post in overlays'''
	def __init__(self,func,ret=0,nodoc=False):
		self.func = func
		self.ret = ret
		
		if not nodoc:
			docText = func.__doc__
			if docText is not None:
				if ret == 0:
					docText += " (keeps overlay open)"
				elif ret == -1:
					docText += " (and close overlay)"
			self.__doc__ = docText	#preserve documentation text

	def __call__(self,*args):
		self.func(*args)
		return self.ret

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
			3:		lambda x: self.parent.stop()
			,27:	self._callalt
			#no post on resize
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
				docstring = "(no documentation)"
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
		ret = None
		try:
			_,x,y,_,state = curses.getmouse()
			if state in self._mouse:
				try:
					ret = self._mouse[state](x,y)
				except TypeError:
					ret = self._mouse[state]()
				except Exception as exc:
					raise TypeError("mouse callback does not have "+\
						"either 0 or 2 arguments") from exc
		except curses.error: pass
		chars = [i for i in chars if i != curses.KEY_MOUSE]
		if chars[0] != -1:
			self.parent.loop.create_task(self.runkey(chars))
				
		return ret

	def _post(self):
		'''
		Run after a keypress if the associated function returns boolean false
		If either the keypress or this returns boolean true, the overlay's
		parent redraws
		'''
		return 1

	@asyncio.coroutine
	def runkey(self,chars):
		'''
		Run a key's callback. This expects a single argument: a list of
		numbers terminated by -1
		'''
		try:
			char = _KEY_LUT[chars[0]]
		except: char = chars[0]
			
		#ignore the command character and trailing -1
		#second clause ignores heading newlines
		fun, args = None, None
		if (char in self._keys) and (char == 27 or len(chars) <= 2 or char > 255):
			fun, args = self._keys[char], chars[1:] or [-1]
		elif -1 in self._keys and (char in (9,10,13) or char in range(32,255)):
			fun, args = self._keys[-1],chars[:-1]
		if fun is not None and args is not None:
			try:
				return fun(args) or self._post()
			except TypeError as exc:
				try:
					return fun() or self._post()
				except TypeError:
					raise exc

	@asyncio.coroutine
	def resize(self,newx,newy):
		'''Overridable function. On resize event, all added overlays have this called'''
		pass

	#frontend methods----------------------------
	def add(self):
		'''Finalize setup and add overlay'''
		self.parent.addOverlay(self)

	def remove(self):
		'''Finalize overlay and pop'''
		self.parent.popOverlay(self)

	def swap(self,new):
		'''Pop overlay and add new one in succession.'''
		self.remove()
		new.add()

	def addKeys(self,newFunctions = {},areMethods = 0):
		'''
		Nice method to add keys after instantiation. Support for
		a- (alt keys), or curses keynames.
		'''
		for i,j in newFunctions.items():
			if isinstance(i,str):
				#alt buttons
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
				#mouse buttons
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
				#everything else
				else:
					try:
						i = _VALID_KEYNAMES[i]
					except: raise KeyException("key {} invalid".format(i))
			#everything else after strings have been converted to valid numbers
			if areMethods:
				self._keys[i] = staticize(j)
			else:
				self._keys[i] = staticize(j,self)

	def nomouse(self):
		'''Unbind the mouse from _keys'''
		if curses.KEY_MOUSE in self._keys:
			del self._keys[curses.KEY_MOUSE]

	def noalt(self):
		'''Unbind alt keys'''
		if 27 in self._keys:
			del self._keys[27]

	@classmethod
	def addKey(cls,key):
		if not hasattr(cls,"_addOnInit"):
			cls._addOnInit = {}
		def ret(func):
			cls._addOnInit[key] = func
		return ret

	def getHelpOverlay(self):
		'''Get list of this overlay's keys'''
		def getHelp(me):
			docstring = me.list[me.it]
			helpDisplay = DisplayOverlay(me.parent,docstring)#,keepEmpty=True)
			helpDisplay.addKeys({
				"enter":	quitlambda
			})
			helpDisplay.add()

		#keys are instanced at runtime
		keysList = ListOverlay(self.parent,dir(self))
			
		keysList.addKeys({
			"enter":	getHelp
		})
		return keysList

	def openHelp(self):
		'''Actually add the overlay generated by openHelp'''
		self.getHelpOverlay().add()

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
			,curses.KEY_RIGHT:	staticize(self.text.movepos,1,
									doc="Move cursor right")
			,curses.KEY_LEFT:	staticize(self.text.movepos,-1,
									doc="Move cursor left")
			,curses.KEY_HOME:	staticize(self.text.home)
			,curses.KEY_END:	staticize(self.text.end)
			,520:				staticize(self.text.delnextword)
		})
		self._altkeys.update({
			ord('h'):		self.text.wordback
			,ord('l'):		self.text.wordnext
			,127:			self.text.delword
			,330:			self.text.delnextword	#TODO tmux alternative
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
		#take out characters that can't be decoded
		uni = bytes([i for i in chars if i<256]).decode()
		return self.text.append(self._transformPaste(uni))

	def _onSentinel(self):
		'''Function run when sentinel character is typed at the beginning of the line'''
		pass

	def _transformPaste(self,string):
		return string

	@asyncio.coroutine
	def resize(self,newx,newy):
		'''Adjust scrollable on resize'''
		self.text.setwidth(newx)

	def remove(self):
		'''Pop scrollable on remove'''
		super(TextOverlay,self).remove()
		self.parent.popScrollable(self.text)

	def controlHistory(self,history):
		'''
		Add standard key definitions for controls on History `history`
		and scrollable `scroll`
		'''
		nexthist = lambda: self.text.setstr(history.nexthist(str(self.text)))
		prevhist = lambda: self.text.setstr(history.prevhist(str(self.text)))
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
	def __init__(self,parent,outList,drawOther = None,modes = [""]):
		super(ListOverlay, self).__init__(parent)
		self.it = 0
		self.mode = 0
		if type(outList) == tuple and len(outList) == 2 and \
		callable(outList[0]):
			self.builder, self.raw = outList
			self.list = self.builder(self.raw)
		else:
			self.builder, self.raw = None, None
			self.list = outList
		self._drawOther = drawOther
		self._modes = modes
		self._nummodes = len(modes)
		self._numentries = len(self.list)

		up =	staticize(self.increment,-1,
			doc="Up one list item")
		down =	staticize(self.increment,1,
			doc="Down one list item")
		right =	staticize(self.chmode,1,
			doc=(self._nummodes and "Go to next mode" or None))
		left =	staticize(self.chmode,-1,
			doc=(self._nummodes and "Go to previous mode" or None))

		self._keys.update(
			{ord('r')-ord('a')+1:	self.regenList
			,ord('j'):	down	#V I M
			,ord('k'):	up
			,ord('l'):	right
			,ord('h'):	left
			,ord('H'):	self.openHelp
			,ord('g'):	staticize(self.gotoEdge,1)
			,ord('G'):	staticize(self.gotoEdge,0)
			,ord('q'):	quitlambda
			,curses.KEY_DOWN:	down
			,curses.KEY_UP:		up
			,curses.KEY_RIGHT:	right
			,curses.KEY_LEFT:	left
		})
		def tryEnter():
			'''Run enter (if it exists)'''
			selectFun = self._keys.get(10)
			if callable(selectFun):
				return selectFun()
		def click(_,y):
			'''Run enter on the element of the list that was clicked'''
			#Manipulate self.it and tryEnter
			#y in the list
			size = self.parent.y - 2
			#borders
			if not y in range(1,size+1): return
			newit = (self.it//size)*size + (y - 1)
			if newit >= len(self.list): return
			self.it = newit
			return tryEnter()
		self._mouse.update(
			{_MOUSE_BUTTONS["left"]:		click
			,_MOUSE_BUTTONS["right"]:		override(click)	#with no return -1
			,_MOUSE_BUTTONS["middle"]:		staticize(tryEnter)
			,_MOUSE_BUTTONS["wheel-up"]:	up
			,_MOUSE_BUTTONS["wheel-down"]:	down
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
				self._drawOther(self,row,i+partition)
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

	def gotoEdge(self,isBeginning):
		'''Move to the end of the list, unless specified to be the beginning'''
		if isBeginning:
			self.it = 0
		else:
			self.it = self._numentries-1

	def regenList(self,_):
		'''Regenerate list based on raw list reference'''
		if self.raw: 
			self.list = self.builder(self.raw)
			self._numentries = len(self.list)

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
			divs = [divmod(i*6/255,1)[1] for i in initcolor]
			#if each error is low enough to be looked for
			if all([i < .05 for i in divs]):
				for i,j in enumerate(self._spectrum[:3]):
					find = j.index([k[0] for k in divs])
					if find+1:
						self.it = find
						self.mode = i
						break
				self.it = len(self._COLOR_LIST)-1
			else:
				self.it = len(self._COLOR_LIST)-1

	def drawColors(self,_,string,i):
		#4 is reserved for color sliders
		if i == 12: return
		color = None
		try:
			which = self._spectrum[self.mode][i]
			if self.mode == 3: #grayscale
				color = (which * 2) + 232
			else:
				color = sum(map(lambda x,y:x*y,which,[36,6,1])) + 16
			string.insertColor(-1,self.parent.get256color(color))
			string.effectRange(-1,0,0)
		except DisplayException:
			pass

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

		spectrum = [item for i in [rspec,yspec,cspec,bspec,ispec,mspec]
			for item in i]

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
			names += self.NAMES[i].center(wide) + CLEAR_FORMATTING
			vals += str(self.color[i]).center(wide) + CLEAR_FORMATTING
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
	'''Creates a future for the contents of a Scrollable input'''
	replace = False
	def __init__(self, parent, prompt, callback = None, password = False):
		super(InputOverlay, self).__init__(parent)
		self._future = parent.loop.create_future()
		self._prompt = prompt if isinstance(prompt,Coloring) else Coloring(prompt)
		self._prompts = self._prompt.breaklines(parent.x-2)
		self._numprompts = len(self._prompts)

		self.text.password = password
		self._keys.update({
			10:		staticize(self._finish)
			,127:	staticize(self._backspacewrap)
		})
		if callable(callback):
			self.runOnDone(callback)

	result = property(lambda self: self._future)

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

	@asyncio.coroutine
	def resize(self,newx,newy):
		'''Resize prompts'''
		yield from super(InputOverlay,self).resize(newx,newy)
		self._prompts = self._prompt.breaklines(parent.x-2)
		self._numprompts = len(self._prompts)

	def _backspacewrap(self):
		'''Backspace a char, or quit out if there are no chars left'''
		if not str(self.text): return -1
		self.text.backspace()

	def _finish(self):
		'''Regular stop (i.e, with enter)'''
		self._future.set_result(str(self.text))
		return -1

	def remove(self):
		'''Cancel future unless future completed'''
		if not self._future.done():
			self._future.cancel()
		super(InputOverlay,self).remove()

	def runOnDone(self,func):
		'''Attach a callback to the future'''
		def callback(future):
			if future.cancelled(): return
			if asyncio.iscoroutinefunction(func):
				self.parent.loop.create_task(func(future.result()))
			else:
				func(future.result())
		self._future.add_done_callback(callback)

class DisplayOverlay(OverlayBase,Box):
	'''Overlay that displays a string in a box'''
	def __init__(self,parent,strings,outdent=""):
		super(DisplayOverlay,self).__init__(parent)
		if isinstance(strings,str) or isinstance(strings,Coloring):
			strings = [strings]
		self.rawlist = [i if isinstance(i,Coloring) else Coloring(i) for i in strings]
		self.outdent = outdent
#		self.keepEmpty = keepEmpty
		
		#flattened list of broken strings
		self.formatted = [j	for i in self.rawlist
			for j in i.breaklines(self.parent.x-2,outdent=outdent)]
		[perror(repr(i)) for i in strings]
		[perror(repr(i)) for i in self.formatted]
		self._numprompts = len(self.formatted)
		#bigger than the box holding it
		if self._numprompts > self.parent.y-2:
			self.replace = True
		else:
			self.replace = False

		self.begin = 0	#begin from this prompt
		up = staticize(self.scroll,-1,
			doc="Scroll downward")
		down = staticize(self.scroll,1,
			doc="Scroll upward")
		self._keys.update({
			curses.KEY_UP:		up
			,curses.KEY_DOWN:	down
			,ord('k'):			up
			,ord('j'):			down
			,ord('q'):			quitlambda
		})
	
	@asyncio.coroutine
	def __call__(self,lines):
		begin = (not self.replace and max((self.parent.y-2)//2 - \
			 self._numprompts//2,0) ) or 0
		i = 0
		lines[begin] = self.box_top()
		for i in range(min(self._numprompts,len(lines)-2)):
			lines[begin+i+1] = self.box_part(self.formatted[self.begin+i])
		if self.replace:
			while i < len(lines)-3:
				lines[begin+i+2] = self.box_part("")
				i+=1
		lines[begin+i+2] = self.box_bottom()

	@asyncio.coroutine
	def resize(self,newx,newy):
		self.formatted = [j	for i in self.rawlist
			for j in i.breaklines(self.parent.x-2,outdent=outdent)]
		self._numprompts = len(self.formatted)
		#bigger than the box holding it
		if self._numprompts > self.parent.y-2:
			#stop drawing the overlay behind it
			self.replace = True
		else:
			self.replace = False

	def scroll(self,amount):
		maxlines = self.parent.y-2
		if (self._numprompts <= maxlines): return
		self.begin = min(max(0,self.begin+amount),maxlines-self._numprompts)

class DisplayOverlayOld(OverlayBase,Box):
	'''Overlay that displays a string in a box'''
	def __init__(self,parent,string,outdent="",keepEmpty=False):
		super(DisplayOverlay,self).__init__(parent)
		self._string = string if isinstance(string,Coloring) else Coloring(string)
		self.outdent = outdent
		self.keepEmpty = keepEmpty

		self.strings = \
			self._string.breaklines(self.parent.x-2,outdent=outdent
			,keepEmpty=keepEmpty)
		self._numprompts = len(self.strings)
		#bigger than the box holding it
		if self._numprompts > self.parent.y-2:
			self.replace = True
		else:
			self.replace = False

		self.begin = 0	#begin from this prompt
		up = staticize(self.scroll,-1,
			doc="Scroll downward")
		down = staticize(self.scroll,1,
			doc="Scroll upward")
		self._keys.update({
			curses.KEY_UP:		up
			,curses.KEY_DOWN:	down
			,ord('k'):			up
			,ord('j'):			down
			,ord('q'):			quitlambda
		})
	
	@asyncio.coroutine
	def __call__(self,lines):
		begin = (not self.replace and max((self.parent.y-2)//2 - \
			 self._numprompts//2,0) ) or 0
		i = 0
		lines[begin] = self.box_top()
		for i in range(min(self._numprompts,len(lines)-2)):
			lines[begin+i+1] = self.box_part(self.strings[self.begin+i])
		if self.replace:
			while i < len(lines)-3:
				lines[begin+i+2] = self.box_part("")
				i+=1
		lines[begin+i+2] = self.box_bottom()

	@asyncio.coroutine
	def resize(self,newx,newy):
		self.strings = \
			self._string.breaklines(self.parent.x-2,outdent=self.outdent
			,keepEmpty=self.keepEmpty)
		self._numprompts = len(self.strings)
		#bigger than the box holding it
		if self._numprompts > self.parent.y-2:
			self.replace = True
		else:
			self.replace = False

	def scroll(self,amount):
		maxlines = self.parent.y-2
		if (self._numprompts <= maxlines): return
		self.begin = min(max(0,self.begin+amount),maxlines-self._numprompts)

class CommandOverlay(TextOverlay):
	'''Overlay to run commands'''
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
		self.controlHistory(self.history)
		self._keys.update({
			10:		self._run
			,127:	self._backspacewrap
		})
		self._altkeys.update({
			127:	lambda: -1
		})

	@asyncio.coroutine
	def __call__(self,lines):
		lines[-1] = "COMMAND"

	def _onSentinel(self):
		if self.caller:
			#get the highest mainOverlay
			self.caller.text.append(CHAR_COMMAND)
		return -1

	def _backspacewrap(self,*args):
		'''Backspace a char, or quit out if there are no chars left'''
		if not str(self.text): return -1
		self.text.backspace()

	def _run(self,*args):
		'''Run command'''
		text = str(self.text)
		self.history.append(text)
		args = text.split(' ')
		if args[0] not in _commands:
			self.parent.newBlurb("Command \"{}\" not found".format(args[0]))
			return -1
		command = _commands[args[0]]
		
		@asyncio.coroutine
		def runCommand():
			try:
				result = command(self.parent,*args[1:])
				if asyncio.iscoroutine(result):
					result = yield from result
				if isinstance(result,OverlayBase):
					result.add()
			except Exception as exc:
				self.parent.newBlurb(
					'an error occurred while running command {}'.format(args[0]))
				perror(traceback.format_exc(),"\n")
		self.parent.loop.create_task(runCommand())
		return -1

class EscapeOverlay(OverlayBase):
	'''Overlay for redirecting input after \ is pressed'''
	replace = False
	def __init__(self,parent,scroll):
		super(EscapeOverlay, self).__init__(parent)
		self._keys.update({
			-1:		quitlambda
			,9:		override(staticize(scroll.append,'\t'),-1,nodoc=True)
			,10:	override(staticize(scroll.append,'\n'),-1,nodoc=True)
			,ord('n'):	override(staticize(scroll.append,'\n'),-1,nodoc=True)
			,ord('\\'):	override(staticize(scroll.append,'\\'),-1,nodoc=True)
			,ord('t'):	override(staticize(scroll.append,'\t'),-1,nodoc=True)
		})
		self.nomouse()
		self.noalt()

class ConfirmOverlay(OverlayBase):
	'''Overlay to confirm selection confirm y/n (no slash)'''
	replace = False
	def __init__(self,parent,confirmfunc):
		super(ConfirmOverlay, self).__init__(parent)
		def callback(*args):
			if asyncio.iscoroutine(confirmfunc):
				self.parent.loop.create_task(confirmfunc)
			else:
				self.parent.loop.call_soon(confirmfunc)
			self.parent.releaseBlurb()
			return -1
		self._keys.update( #run these in order
			{ord('y'):	callback
			,ord('n'):	override(staticize(self.parent.releaseBlurb),-1)
		})
		self.nomouse()
		self.noalt()

class BlockingOverlay(OverlayBase):
	'''Block until any input is received'''
	replace = False
	def __init__(self,parent,confirmfunc,tag=""):
		super(BlockingOverlay, self).__init__(parent)
		self.tag = tag
		def callback(*args):
			if asyncio.iscoroutine(confirmfunc):
				self.parent.loop.create_task(confirmfunc)
			else:
				self.parent.loop.call_soon(confirmfunc)
			return -1
		self._keys.update({-1: callback})
		self.nomouse()
		self.noalt()

	def add(self):
		if self.tag:
			for i in self.parent.getOverlaysByClassName(type(self).__name__):
				#don't add overlays with the same tag
				if i.tag == self.tag: return
		super(BlockingOverlay, self).add()

class Messages:
	'''Container object for message objects'''
	_INDENT = "    "
	def __init__(self,parent):
		self.clear()
		self.parent = parent
		
	def clear(self):
		'''Clear all lines and messages'''
		self.canselect = True
		#these two REALLY should be private
		self.allMessages = []
		self.lines = []
		self.msgID = 0				#next message id
		#these too because they select the previous two
		self.selector = 0			#messages from the bottom
		self.linesup = 0			#lines up from the bottom
		self.innerheight = 0		#inner message height, for ones too big
		#recolor
		self.lastRecolor = -1		#highest recolor ID (updated on recolorlines)
		self.lastFilter = -1		#highest filter ID (updated on redolines)
		self.lazyDelete = []		#list of message ids to delete when they become visible

	def stopSelect(self):
		'''Stop selecting'''
		if self.selector:
			self.selector = 0
			self.linesup = 0
			self.innerheight = 0
			return 1

	def getselected(self):
		'''
		Frontend for getting the selected message. Returns a 4-list:
		[0]: the message (in a coloring object); [1] an argument tuple, which
		is None for system messages; [2] the number of lines it occupies;
		[3]: its messageID
		returns False on not selecting
		'''
		if self.selector:
			return self.allMessages[-self.selector]
		return False

	def display(self,lines):
		if self.msgID == 0: return
		#seperate traversals
		selftraverse,linetraverse = -1,-2
		lenself, lenlines = len(self.lines),len(lines)
		msgno = 1
		#go backwards by default
		direction = -1
		#if we need to go forwards
		if self.linesup-self.innerheight >= lenlines:
			direction = 1
			msgno = self.selector
			selftraverse,linetraverse = -self.linesup+self.innerheight,-lenlines
			lenself, lenlines = -1,-2

		thismsg = self.allMessages[-msgno][2]
		#traverse list of lines
		while (selftraverse*direction) <= lenself and \
		(linetraverse*direction) <= lenlines:
			reverse = (msgno == self.selector) and SELECT_AND_MOVE or ""
			lines[linetraverse] = reverse + self.lines[selftraverse]
			selftraverse += direction
			linetraverse += direction
			#adjust message number for highlighting selected
			thismsg -= 1
			while not thismsg:
				msgno -= direction
				if msgno <= len(self.allMessages):
					thismsg = self.allMessages[-msgno][2]
				else:
					break

	def scroll(self,step):
		'''Select message. Only use step values of 1 and -1'''
		#scroll back up the message
		if step > 0 and self.innerheight:
			self.innerheight -= 1
			return 0
		tooBig = self.allMessages[-self.selector][2] - (self.parent.parent.y-1)
		#downward, so try to scroll the message downward
		if step < 0 and tooBig > 0:
			if self.innerheight < tooBig:
				self.innerheight += 1
				return 0
		#otherwise, try to find next message
		select = self.selector+step
		addlines = 0
		#get the next message, applying colors/filters as appropriate
		while not addlines and select <= len(self.allMessages):
			message = self.allMessages[-select]

			#test all lazy deleters
			for test,result in self.lazyDelete:
				if test(message,result):
					del self.allMessages[-select]

			#lazy filters
			if message[3] == self.lastFilter:
				#use a dummy length to signal that the message should be drawn
				message[2] = ((message[1] is None) or \
					not self.parent.filterMessage(*message[1]))
				if select < len(self.allMessages):
					self.lastFilter = self.allMessages[-select-1][3]
				else:
					self.lastFilter = -1

			if message[3] == self.lastRecolor:
				#ignore system
				if (message[1] is not None):
					self.parent.colorizeMessage(message[0],*message[1])
				if select < len(self.allMessages):
					self.lastRecolor = self.allMessages[-select-1][3]
				else:
					self.lastRecolor = -1

			#adjust linesup if scrolling down
			if step > 0 and message[2]:
				#for formerly invisible messages
				self.linesup += message[2]	#'go up' if unfiltered
				if self.linesup > len(self.lines):
					new = message[0].breaklines(self.parent.parent.x,self._INDENT)
					#do it in-place instead of making a new list
					self.lines[0:0] = new
					numnew = len(new)
					self.linesup += (numnew - message[2])
					message[2] = numnew

			addlines = message[2]
			select += step

		#adjust linesup if scrolling down
		lastLength = self.allMessages[-self.selector][2]
		if step < 0 and lastLength:
			self.linesup = max(0,self.linesup-lastLength)

		#if we're even "going" anywhere
		if (select - step - self.selector) and addlines:
			self.selector = max(0,select - step)
			self.innerheight = 0
		return addlines

	def append(self,message,args = None):
		'''Add new message to the end of allMessages and lines'''
		#undisplayed messages have length zero
		msg = [message,args,0,self.msgID]
		self.msgID += 1
		self.allMessages.append(msg)
		#before we filter it
		self.selector += (self.selector>0)
		#run filters
		if (args is not None) and self.parent.filterMessage(*args):
			return msg[-1]
		new = message.breaklines(self.parent.parent.x,self._INDENT)
		self.lines.extend(new)
		msg[2] = len(new)
		#keep the right message selected
		if self.selector:
			self.linesup += msg[2]
		return msg[-1]

	def prepend(self,message,args = None):
		'''Prepend new message. Use msgPrepend instead'''
		#run filters early so that the message can be selected up to properly
		dummyLength = not self.parent.filterMessage(*args) if args is not None else 1
		msg = [message, args, dummyLength, self.msgID]
		self.msgID += 1
		self.allMessages.insert(0,msg)
		#we actually need to draw it
		#(like for adding historical messages chronologically while empty)
		if dummyLength and self.linesup < (self.parent.parent.y-1):
			new = message.breaklines(self.parent.parent.x,self._INDENT)
			self.lines[0:0] = new
			msg[2] = len(new)

		return msg[-1]

	def delete(self,result,test=lambda x,y: x[3] == y):
		'''Delete message from value result and callable test'''
		nummsg = 1
		if not callable(test): return
		#if all messages are length 1, then that's our maximum tolerance
		#for laziness
		bound = min(self.parent.parent.y-1,len(self.allMessages))
		#selecting up too high
		if self.linesup-self.innerheight >= bound:
			bound = self.selector
			
		while nummsg <= bound:
			if (test(self.allMessages[-nummsg],result)):
				del self.allMessages[-nummsg]
				return
			nummsg += 1

		self.lazyDelete.append(test,result)

	def getMessageFromPosition(self,x,y):
		'''Get the message and depth into the string at position x,y'''
		if y >= self.parent.parent.y-1: return "",-1
		#go up or down
		direction = 1
		msgNo = 1
		height = 0
		if self.linesup < self.parent.parent.y-1:
			#"height" from the top
			y = self.parent.parent.y - 1 - y
		else:
			direction = -1
			msgNo = self.selector
			y = y + 1
		#find message until we exceed the height
		msg = self.allMessages[-msgNo]
		while msgNo <= len(self.allMessages) and height < y:
			msg = self.allMessages[-msgNo]
			height += msg[2]
			msgNo += direction

		#for at the bottom (drawing up) line depth is simply height-y
		depth = height-y + self.innerheight
		firstLine = height 
		
		#for drawing down, we're going backwards, so we have to subtract msg[2]
		if direction-1:
			depth = msg[2] - depth - 1
			firstLine = msg[2] + self.linesup - height

		#adjust the position
		pos = 0
		for i in range(depth):
			pos += numdrawing(self.lines[i-firstLine]) - len(self._INDENT)
		if x >= collen(self._INDENT):
			#try to get a slice up to the position 'x'
			pos += columnslice(self.lines[depth-firstLine],x)
			
		return msg,pos

	#REAPPLY METHODS-----------------------------------------------------------
	@asyncio.coroutine
	def redolines(self, width = None, height = None):
		'''
		Redo lines, if current lines does not represent the unfiltered messages
		or if the width has changed
		'''
		if width is None: width = self.parent.parent.x
		if height is None: height = self.parent.parent.y
		newlines = []
		numup,nummsg = 0,1
		#while there are still messages to add (to the current height)
		#feels dirty and slow, but this will also resize all messages below
		#the selection
		while (nummsg <= self.selector or numup < height) and \
		nummsg <= len(self.allMessages):
			i = self.allMessages[-nummsg]
			#check if the message should be drawn
			if (i[1] is not None) and self.parent.filterMessage(*i[1]):
				i[2] = 0
				nummsg += 1
				continue
			new = i[0].breaklines(width,self._INDENT)
			newlines[0:0] = new
			i[2] = len(new)
			numup += i[2]
			if nummsg == self.selector: #invalid always when self.selector = 0
				self.linesup = numup
			nummsg += 1
		#nummsg starts at 1, so to compare with allMessages, 1 less
		self.lastFilter = -1	if nummsg-1 == len(self.allMessages) \
								else self.allMessages[-nummsg][3]
		self.lines = newlines
		self.canselect = True

	@asyncio.coroutine
	def recolorlines(self):
		'''Re-apply parent's colorizeMessage and redraw all visible lines'''
		width = self.parent.parent.x
		height = self.parent.parent.y
		newlines = []
		numup,nummsg = 0,1
		while (numup < height or nummsg <= self.selector) and \
		nummsg <= len(self.allMessages):
			i = self.allMessages[-nummsg]
			if i[1] is not None:	#don't decolor system messages
				i[0].clear()
				self.parent.colorizeMessage(i[0],*i[1])
			nummsg += 1
			if i[2]: #unfiltered (non zero lines)
				new = i[0].breaklines(width,self._INDENT)
				newlines[0:0] = new
				i[2] = len(new)
				numup += i[2]
		self.lastRecolor = -1	if nummsg-1 == len(self.allMessages) \
								else self.allMessages[-nummsg][3]
		self.lines = newlines

class MainOverlay(TextOverlay):
	'''
	Overlay that can push and select messages, and has an input box.
	Optionally pushes time messages every 10 minutes and refreshes 
	blurbs every few seconds
	'''
	replace = True
	_monitors = {}
	def __init__(self,parent,pushtimes = True):
		super(MainOverlay, self).__init__(parent)
		self._sentinel = ord(CHAR_COMMAND)
		self._pushtimes = pushtimes
		self.history = History()
		self.messages = Messages(self)
		self.controlHistory(self.history)
		self._keys.update({
			ord('\\'):		self._replaceback
		})
		self._altkeys.update({
			ord('k'):		self.selectup
			,ord('j'):		self.selectdown
		})
		self._mouse.update({
			_MOUSE_BUTTONS["wheel-up"]:		self.selectup
			,_MOUSE_BUTTONS["wheel-down"]:	self.selectdown
		})
		examiners = self._monitors.get(type(self).__name__)
		if examiners is not None:
			self._examine = examiners
		else:
			self._examine = []

	@asyncio.coroutine
	def __call__(self,lines):
		'''Display messages'''
		self.messages.display(lines)
		lines[-1] = Box.CHAR_HSPACE*self.parent.x

	#method overloading---------------------------------------------------------
	def _onSentinel(self):
		'''Input some text, or enter CommandOverlay when CHAR_CURSOR typed'''
		CommandOverlay(self.parent,self).add()

	def _post(self):
		if self.messages.stopSelect():
			self.innerheight = 0
			#put the cursor back
			self.parent.loop.create_task(self.parent.updateinput())
			return 1

	def add(self):
		'''Start timeloop and add overlay'''
		super(MainOverlay,self).add()
		if self._pushtimes:
			self._pushTask = self.parent.loop.create_task(self._timeloop())

	def remove(self):
		'''
		Quit timeloop (if it hasn't already exited).
		Exit client if last overlay.
		'''
		if self._pushtimes:
			#finish running the task
			self._pushtimes = False
#			self.parent.loop.call_soon(self._pushTask.cancel)
			self._pushTask.cancel()
		if not self.index:
			self.parent.active = False
		super(MainOverlay,self).remove()

	@asyncio.coroutine
	def resize(self,newx,newy):
		'''Resize scrollable and maybe draw lines again if width changed'''
		yield from super(MainOverlay,self).resize(newx,newy)
		yield from self.messages.redolines(newx,newy)

	def clear(self):
		'''Clear all lines and messages'''
		self.canselect = True
		self.messages.clear()
		
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

	@asyncio.coroutine
	def _timeloop(self):
		'''Prints the current time every 10 minutes. Also handles erasing blurbs'''
		i = 0
		while self._pushtimes:
			yield from asyncio.sleep(2)
			i+=1
			if self.parent.loop.time() - self.parent.last > 4:	#erase blurbs
				self.parent.newBlurb()
			#every 600 seconds
			if not i % 300:
				yield from self.msgTime()
				i=0

	def _replaceback(self,*args):
		'''
		Add a newline if the next character is n, 
		or a tab if the next character is t
		'''
		EscapeOverlay(self.parent,self.text).add()

	#MESSAGE SELECTION----------------------------------------------------------
	def _maxselect(self):
		soundBell()

	def selectup(self):
		'''Select message up'''
		if not self.canselect: return 1
		#go up the number of lines of the "next" selected message
		upmsg = self.messages.scroll(1)
		#but only if there is a next message
		if not upmsg: self._maxselect()
		return 1

	def selectdown(self):
		'''Select message down'''
		if not self.canselect: return 1
		#go down the number of lines of the currently selected message
		self.messages.scroll(-1)
		if not self.messages.selector:
			#move the cursor back
			self.parent.loop.create_task(self.parent.updateinput())
		return 1

	def redolines(self):
		self.parent.loop.create_task(self.messages.redolines())
		self.parent.loop.create_task(self.parent.display())
		
	def recolorlines(self):
		self.parent.loop.create_task(self.messages.recolorlines())
		self.parent.loop.create_task(self.parent.display())

	#MESSAGE ADDITION----------------------------------------------------------
	@asyncio.coroutine
	def msgSystem(self, base):
		'''System message'''
		base = Coloring(base)
		base.insertColor(0,rawNum(1))
		self.messages.append(base,None)
		yield from self.parent.display()
	@asyncio.coroutine
	def msgTime(self, numtime = None, predicate=""):
		'''Push a system message of the time'''
		dtime = format_time("%H:%M:%S",localtime(numtime or time()))
		yield from self.msgSystem(predicate+dtime)
	@asyncio.coroutine
	def msgPost(self,post,*args):
		'''Parse a message, apply colorizeMessage, and append'''
		post = Coloring(post)
		self.colorizeMessage(post,*args)
		ret = self.messages.append(post,list(args))
		for i in self._examine:
			i(self,post,*args)
		yield from self.parent.display()
		return ret
	@asyncio.coroutine
	def msgPrepend(self,post,*args):
		'''Parse a message, apply colorizeMessage, and prepend'''
		post = Coloring(post)
		self.colorizeMessage(post,*args)
		ret = self.messages.prepend(post,list(args))
		yield from self.parent.display()
		return ret
	@asyncio.coroutine
	def msgDelete(self,number):
		self.messages.delete(number)

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
		self.parent.loop.create_task(self.parent.updateinput())

#MAIN CLIENT--------------------------------------------------------------------

class Main:
	'''Main class; handles all IO and defers to overlays'''
	last = 0
	def __init__(self,loop=None):
		self.loop = asyncio.get_event_loop() if loop is None else loop
		#general state
		self.active = True
		self.candisplay = False
		self.prepared = asyncio.Event(loop=self.loop)
		self.exited = asyncio.Event(loop=self.loop)
		#guessed terminal dimensions
		self.x = 40
		self.y = 70
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
		if not (self.active and self.candisplay): return
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
		print(end="\x1b[?25l")
		#draw each line in lines, deleting the rest of the garbage on the line
		for i in lines:
			print(i,end="\x1b[K\n\r") 
		print(CHAR_RETURN_CURSOR,end="")

	@asyncio.coroutine
	def updateinput(self):
		'''Input display backend'''
		if not (self.active and self.candisplay): return
		if not self._scrolls: return	#no textoverlays added
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
			self._blurbQueue = blurb.breaklines(self.x)
		else:
			self._blurbQueue = Coloring(blurb).breaklines(self.x)
		#next blurb is either a pop from the last message or nothing
		if len(self._blurbQueue):
			blurb = self._blurbQueue.pop(0)
		else:
			blurb = ""
		self.last = time
		_moveCursor(self.y+2)
		print("{}\x1b[K".format(blurb),end=CHAR_RETURN_CURSOR)

	@asyncio.coroutine
	def _updateinfo(self,right=None,left=None):
		'''Info window backend'''
		if not (self.active and self.candisplay): return
		self._bottom_edges[0] = str(left or self._bottom_edges[0])
		self._bottom_edges[1] = str(right or self._bottom_edges[1])
		room = self.x - collen(self._bottom_edges[0]) - collen(self._bottom_edges[1])
		if room < 1: return

		_moveCursor(self.y+3)
		#selected, then turn off
		print("\x1b[7m{}{}{}\x1b[0m".format(self._bottom_edges[0],
			" "*room,self._bottom_edges[1]),end=CHAR_RETURN_CURSOR)

	#Display Frontends----------------------------------------------------------
	def newBlurb(self,message = ""):
		'''Add blurb. Use in conjunction with MainOverlay to erase'''
		self.loop.create_task(self._printblurb(message,self.loop.time()))

	def holdBlurb(self,message):
		'''Hold blurb. Sets self.last to -1, making newBlurb not draw'''
		self.loop.create_task(self._printblurb(message,-1))

	def releaseBlurb(self):
		'''
		Release blurb. Sets self.last to a valid time, making newBlurb
		start drawing again.
		'''
		self.loop.create_task(self._printblurb(message,"",self.loop.time()))

	def updateinfo(self,right = None,left = None):
		'''Update screen bottom'''
		self.loop.create_task(self._updateinfo(right,left))
	#Overlay Frontends---------------------------------------------------------
	def addOverlay(self,new):
		'''Add overlay'''
		if not isinstance(new,OverlayBase): return
		new.index = len(self._ins)
		self._ins.append(new)
		if new.replace: self._lastReplace = new.index
		#display is not strictly called beforehand, so better safe than sorry
		self.loop.create_task(self.display())

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
		self.loop.create_task(self.display())

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
		nextch = -1
		while nextch == -1:
			nextch = self._screen.getch()
			yield from asyncio.sleep(.01)

		#we need this here so that _input doesn't lock up the rest of the loop
		#and we return to the event loop at least once with `yield from sleep`;
		if not self._ins: return

		chars = [nextch]
		while nextch != -1:
			nextch = self._screen.getch()
			chars.append(nextch)
		ret = yield from self._ins[-1].runkey(chars)

		return ret

	@asyncio.coroutine
	def run(self):
		'''Main client loop'''
		#interactivity when using a main instance
		if not (sys.stdin.isatty() and sys.stdout.isatty()):
			raise ImportError("interactive stdin/stdout required to run Main")
		if sys.stderr.isatty():
			sys.stderr = open("/tmp/client.log","a+")
		#curses input setup
		self._screen = curses.initscr()		#init screen
		curses.noecho(); curses.cbreak(); self._screen.keypad(1) #setup curses
		self._screen.nodelay(1)	#don't wait for enter to get input
		self._screen.getch() #the first getch clears the screen

		#escape has delay, not that this matters since I embed this in tmux
		os.environ.setdefault("ESCDELAY", "25")
		#pass in the control chars for ctrl-c and ctrl-z
		self.loop.add_signal_handler(SIGINT,lambda: curses.ungetch(3))
		self.loop.add_signal_handler(SIGTSTP,lambda: curses.ungetch(26))

		yield from self.resize()
		self.prepared.set()

		try:
			#done for now; call coroutines waiting for preparation
			while self.active:
				inp = yield from self._input()
				if inp:	
					if inp == -1:
						self._ins[-1].remove()
					yield from self.display()
		except asyncio.CancelledError: pass	#catch cancellations
		finally:
			self.active = False
			#let overlays do cleanup
			for i in reversed(self._ins):
				try:
					i.remove()
				except: pass
			#return to sane mode
			curses.echo(); curses.nocbreak(); self._screen.keypad(0)
			curses.endwin()
			self.loop.remove_signal_handler(SIGINT)
			self.loop.remove_signal_handler(SIGTSTP)
			for i in _afterDone:
				yield from i
			self.exited.set()

	def start(self):
		return self.loop.create_task(self.run())

	def stop(self):
		curses.ungetch(27)
		self.active = False
		
	#Frontends------------------------------------------------------------------
	@asyncio.coroutine
	def resize(self):
		'''Resize the GUI'''
		newy, newx = self._screen.getmaxyx()
		#magic number, but who cares; one for text,
		#one for blurbs, one for reverse info
		newy -= 3
		try:
			for i in self._ins:
				yield from i.resize(newx,newy)
		except SizeException:
			self.x,self.y = newx,newy
			self.candisplay = 0
			return
		self.x,self.y = newx,newy
		self.candisplay = 1
		yield from self.display()
		yield from self._updateinfo()
		yield from self.updateinput()

	def toggle256(self,value):
		'''Turn the mode to 256 colors, and if undefined, define colors'''
		self._two56 = value
		if value and not hasattr(self,"two56start"): #not defined on startup
			self._two56start = len(_COLORS) + rawNum(0)
			def256colors()

	def toggleMouse(self,state):
		'''Turn the mouse on or off'''
		return curses.mousemask(state and _MOUSE_MASK)

	def get256color(self,color):
		'''
		Convert a hex string to 256 color variant or get
		color as a pre-caluclated number from `color`
		Raises DisplayException if not running in 256 color mode
		'''
		if not self._two56: raise DisplayException("Not running in 256 color mode")

		if isinstance(color,int):
			return self._two56start + color
			
		if color is None or len(color) < 3 or len(color) % 3:
			return rawNum(0)
		partsLen = len(color)//3
		in216 = [int(int(color[i*partsLen:(i+1)*partsLen],16)*6/(16**partsLen))
			 for i in range(3)]
		#too white or too black
		if sum(in216) < 2 or sum(in216) > 34:
			return rawNum(0)
		return self._two56start + 16 + sum(map(lambda x,y: x*y,in216,[36,6,1]))

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
	parent.stop()
