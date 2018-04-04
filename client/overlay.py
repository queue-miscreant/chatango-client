#!/usr/bin/env python3
#client.overlay.py
'''
Client module with single-byte curses input uses a system of overlays, sending
input to the topmost one. Output is not done with curses display, but line-by-
line writing to the terminal buffer (the Main instance reassigns `sys.stdout`
to a temporary file to keep output clean)
'''
try:
	import curses
except ImportError:
	raise ImportError("Could not import curses; is this running on Windows cmd?")

import sys
import os
import asyncio
import traceback
from signal import SIGTSTP,SIGINT #redirect ctrl-z and ctrl-c
from inspect import getdoc
from time import time,localtime,strftime as format_time
from .display import *
from .util import staticize,override,escapeText,LazyIterList,History

__all__ =	["CHAR_COMMAND","quitlambda","Box","OverlayBase","TextOverlay"
			,"InputOverlay","ListOverlay","VisualListOverlay","ColorOverlay"
			,"ColorSliderOverlay","ConfirmOverlay","CommandOverlay"
			,"DisplayOverlay","ChatOverlay","addMessageScroller","InputMux"
			,"Main"]

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

#OVERLAY HELPERS------------------------------------------------------------------
CHAR_COMMAND	= '`'
RETURN_CURSOR	= "\x1b[?25h\x1b[u\n\x1b[A"
#return cursor to the top of the screen, hide, and clear formatting on drawing
DISPLAY_INIT	= "\x1b[;f%s\x1b[?25l" % CLEAR_FORMATTING
#format with tuple (row number, string)
#move cursor, clear formatting, print string, clear garbage, and return cursor
SINGLE_LINE		= "\x1b[%d;f" + CLEAR_FORMATTING +"%s\x1b[K" + RETURN_CURSOR
RESERVE_LINES 	= 3

#DISPLAY CLASSES----------------------------------------------------------
class SizeException(Exception):
	'''
	Exception for errors when trying to display an overlay.
	Should only be raised in an overlay's resize method,
	where if raised, the Main instance will not attempt to display.
	'''

quitlambda = lambda x: -1
quitlambda.__doc__ = "Close current overlay"

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

class _NScrollable(ScrollSuggest):
	'''
	A scrollable that expects a Main object as parent so that it 
	can run Main._updateinput()
	'''
	def __init__(self,parent):
		super(_NScrollable, self).__init__(parent.x)
		self.parent = parent
		self._index = -1
	def _setIndex(self,index):
		self._index = index
	def _onchanged(self):
		super(_NScrollable, self)._onchanged()
		self.parent._updateinput()

#OVERLAYS----------------------------------------------------------------------
class OverlayBase:
	'''
	Virtual class that redirects input to callbacks and modifies a list
	of (output) strings. All overlays must descend from OverlayBase
	'''
	def __init__(self,parent):
		self.parent = parent		#parent
		self.index = None			#index in the stack
		self._keys = {
			3:		staticize(self.parent.stop,doc="Exit client")
			,12:	self.parent.redrawAll
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
			if i in ("^[","^i","^j",chr(127),"mouse"): continue	
			if i == ' ': i = "space"
			docstring = ""
			formatString = ""
			if j in self._keys:
				docstring = getdoc(self._keys[j])
				formatString = "{}: {}"
			elif j in self._altkeys:
				docstring = getdoc(self._altkeys[j])
				formatString = "a-{}: {}"
			else: continue

			if not docstring:
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
		chars = [i for i in chars if i != curses.KEY_MOUSE]
		if chars[0] != -1:
			#loop control is not returned until later
			self.parent.loop.create_task(self.runkey(chars))
		try:
			_,x,y,_,state = curses.getmouse()
			if state in self._mouse:
				try:
					return self._mouse[state](x,y)
				except TypeError:
					return self._mouse[state]()
				except Exception as exc:
					raise TypeError("mouse callback does not have "+\
						"either 0 or 2 arguments") from exc
		except curses.error: pass

	def _post(self):
		'''
		Run after a keypress if the associated function returns value for which
		bool() returns false. If either the keypress or this returns boolean true,
		the overlay issues a redraw to the Main instance
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
			except TypeError:
				return fun() or self._post()

	@asyncio.coroutine
	def resize(self,newx,newy):
		'''
		Overridable function. All added overlays have this method called
		on resize event
		'''
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
							self._altkeys[i] = staticize(j)
						else:
							self._altkeys[i] = staticize(j,self)
						continue
					else: raise KeyException("key alt-{} invalid".format(i))
				#mouse buttons
				elif not i.lower().find("mouse-"):
					i = i[6:]
					if i in _MOUSE_BUTTONS:
						i = _MOUSE_BUTTONS[i]
						if areMethods:
							self._mouse[i] = staticize(j)
						else:
							self._mouse[i] = staticize(j,self)
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
		'''Open help overlay'''
		self.getHelpOverlay().add()

class TextOverlay(OverlayBase):
	'''Virtual overlay with text input (at bottom of screen)'''
	def __init__(self,parent = None):
		super(TextOverlay, self).__init__(parent)
		self.text = _NScrollable(self.parent)
		#ASCII code of sentinel char
		self._sentinel = 0
		self._keys.update({
			-1:				self._input
			,4:				staticize(self.text.clear)
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

	def add(self):
		'''Add scrollable with overlay'''
		super(TextOverlay,self).add()
		self.parent.addScrollable(self.text)

	def remove(self):
		'''Pop scrollable on remove'''
		super(TextOverlay,self).remove()
		self.parent.popScrollable(self.text)

	@asyncio.coroutine
	def resize(self,newx,newy):
		'''Adjust scrollable on resize'''
		self.text.setwidth(newx)

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
		buffer = []
		controlFlag = False
		for i in chars:
			if i == 194 or controlFlag:
				controlFlag ^= 1
				continue
			buffer.append(i)
		if not buffer: return
		uni = bytes(buffer).decode()
		return self.text.append(self._transformPaste(uni))

	def _onSentinel(self):
		'''Function run when sentinel character is typed at the beginning of the line'''
		pass

	def _transformPaste(self,string):
		return string

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
			{ord('r')-ord('a')+1:	self.regenList	#ctrl-r
			,ord('j'):	down	#V I M
			,ord('k'):	up
			,ord('l'):	right
			,ord('h'):	left
			,ord('H'):	self.openHelp
			,ord('g'):	staticize(self.gotoEdge,1,doc="Go to list beginning")
			,ord('G'):	staticize(self.gotoEdge,0,doc="Go to list end")
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

class VisualListOverlay(ListOverlay,Box):
	'''ListOverlay with visual mode like in vim: can select multiple rows'''
	replace = True

	def __init__(self,parent,outList,drawOther = None,modes = [""]):
		#new draw callback that adds an underline to selected elements
		def draw(me,row,pos):
			if pos in me.selectedList():
				row.addGlobalEffect(1)
			drawOther(me,row,pos)
		super(VisualListOverlay,self).__init__(parent,outList,draw,modes)

		self.clear()	#clear/initialize the selected data
		
		self._keys.update(
			{ord('q'):	self.clearQuit
			,ord('s'):	self.toggle
			,ord('v'):	self.toggleSelect
		})

	def clear(self,*args):
		self._selected = set()	#list of indices selected by visual mode
		self._selectBuffer = set()
		self._startSelect = -1

	def increment(self,amt):
		'''New implemetation of increment that updates the visual lines'''
		super(VisualListOverlay,self).increment(amt)
		if self._startSelect + 1: #already selecting
			if self.it < self._startSelect:
				#+1 because toggleselect already toggles the element
				self._selectBuffer = set(range(self.it,self._startSelect))
			else:
				self._selectBuffer = set(range(self._startSelect+1,self.it+1))

	def gotoEdge(self,isBeginning):
		'''Move to the end of the list, unless specified to be the beginning'''
		if isBeginning:
			self.it = 0
			self._selectBuffer = set(range(self.it,self._startSelect+1))
		else:
			self.it = self._numentries-1
			self._selectBuffer = set(range(self._startSelect,self.it+1))

	def toggle(self):
		'''Toggle the current line'''
		self._selected = self._selected.symmetric_difference((self.it,))
	
	def toggleSelect(self):
		'''Toggle visual mode selecting'''
		if self._startSelect + 1:	#already selecting
			#canonize the select
			self._selected = \
				self._selected.symmetric_difference(self._selectBuffer)
			self._selectBuffer = set()
			self._startSelect = -1
			return
		self.toggle()
		self._startSelect = self.it

	def selectedList(self):
		'''Get list (set) of selected and buffered indices'''
		return self._selected.symmetric_difference(self._selectBuffer)

	def clearQuit(self,*args):
		'''Clear the selection or quit the overlay'''
		if self._selectBuffer or self._selected:
			self.clear()
		else:
			return -1

class ColorOverlay(ListOverlay,Box):
	'''Display 3 bars for red, green, and blue. Allows exporting of color as hex'''
	replace = True
	_SELECTIONS = ["normal","shade","tint","grayscale"]
	_COLOR_LIST = ["red","orange","yellow","light green","green","teal",
		"cyan","turquoise","blue","purple","magenta","pink","color sliders"]

	def __init__(self,parent,callback,initcolor=None):
		self._spectrum = self._genspectrum()
		super(ColorOverlay, self).__init__(parent,self._COLOR_LIST,
				self.drawColors, self._SELECTIONS)
		#parse initcolor
		self.initcolor = [127,127,127]
		if type(initcolor) is str and len(initcolor) == 6:
			initcolor = [int(initcolor[i*2:(i+1)*2],16) for i in range(3)]
		if type(initcolor) is list and len(initcolor) == 3:
			self.initcolor = initcolor
			#how much each color corrseponds to some color from the genspecturm
			divs = [divmod(i*5/255,1) for i in initcolor]
			#if each error is low enough to be looked for
			if all([i[1] < .05 for i in divs]):
				for i,j in enumerate(self._spectrum[:3]):
					try:
						find = j.index(tuple(int(k[0]) for k in divs))
						self.it = find
						self.mode = i
						break
					except ValueError: pass
			else:
				self.it = len(self._COLOR_LIST)-1
		self._callback = callback
		self._keys.update({
			9:		self._select	#tab
			,10:	self._select	#enter
			,32:	self._select	#space
		})

	def _select(self):
		'''Open the sliders or run the callback with the selected color'''
		if self.it == 12:
			return self.openSliders()
		return self._callback(self.getColor())

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
		return tuple(int(i*255/5) for i in which)

	def openSliders(self):
		furtherInput = ColorSliderOverlay(self.parent,
			self._callback,self.initcolor)
		self.swap(furtherInput)

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
	'''Display 3 bars for red, green, and blue.'''
	replace = True
	NAMES = ["Red","Green","Blue"]
	def __init__(self,parent,callback,initcolor = [127,127,127]):
		super(ColorSliderOverlay, self).__init__(parent)
		#allow setting from hex value
		if not (isinstance(initcolor,tuple) or isinstance(initcolor,list)):
			raise TypeError("initcolor must be list or tuple")
		self.color = list(initcolor)
		self._updateText()
		self._rgb = 0
		self._callback = callback
		self._keys.update(
			{10:			self._select
			,ord('q'):		quitlambda
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
		lines[-2] = self.box_part(format(self._coloredText).rjust(int(wide*1.5)+3)) #1
		lines[-1] = self.box_bottom() #last line

	def _select(self):
		return self._callback(tuple(self.color))

	#predefined self-traversal methods
	def increment(self,amt):
		'''Increase the selected color by amt'''
		self.color[self._rgb] = max(0,min(255, self.color[self._rgb] + amt))
		self._updateText()

	def chmode(self,amt):
		'''Go to the color amt to the right'''
		self._rgb = (self._rgb + amt) % 3

	def _updateText(self):
		self._coloredText = Coloring(self.toHex(self.color))
		self._coloredText.insertColor(0,self.parent.get256color(self.color))

	@staticmethod
	def toHex(color):
		'''Get self.color in hex form'''
		return ''.join([hex(i)[2:].rjust(2,'0') for i in color])

class InputOverlay(TextOverlay,Box):
	'''Creates a future for the contents of a Scrollable input'''
	replace = False
	def __init__(self, parent, prompt, callback = None, password = False):
		super(InputOverlay, self).__init__(parent)
		self._future = parent.loop.create_future()
		if prompt is None:
			self._prompt, self._prompts, self._numprompts = None, [], 0
		else:
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
		if self._prompt is None: return
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

		self._outdent = outdent
		self.changeDisplay(strings)

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
			,ord('H'):			self.openHelp
		})

	def changeDisplay(self,strings):
		'''Basically re-initialize without making a new overlay'''
		if isinstance(strings,str) or isinstance(strings,Coloring):
			strings = [strings]
		self.rawlist = [i if isinstance(i,Coloring) else Coloring(i) for i in strings]
		
		#flattened list of broken strings
		self.formatted = [j	for i in self.rawlist
			for j in i.breaklines(self.parent.x-2,outdent=self._outdent)]
		self._numprompts = len(self.formatted)
		#bigger than the box holding it
		if self._numprompts > self.parent.y-2:
			self.replace = True
		else:
			self.replace = False

		self.begin = 0	#begin from this prompt

	def forceOutdent(self,outdent):
		self._outdent = outdent
	
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

class CommandOverlay(TextOverlay):
	'''Overlay to run commands'''
	replace = False
	history = History()	#global command history
	#command containers
	_commands = {}
	_commandComplete = {}
	def __init__(self,parent,caller = None):
		super(CommandOverlay,self).__init__(parent)
		self._sentinel = ord(CHAR_COMMAND)
		self.caller = caller
		self.text.setnonscroll(CHAR_COMMAND)
		self.text.completer.addComplete(CHAR_COMMAND,self._commands)
		for i,j in self._commandComplete.items():
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
		#parse arguments like a command line: quotes enclose single args
		args = escapeText(self.text)
		self.history.append(self.text)

		if args[0] not in self._commands:
			self.parent.newBlurb("Command \"{}\" not found".format(args[0]))
			return -1
		command = self._commands[args[0]]
		
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
				print(traceback.format_exc(),"\n")
		self.parent.loop.create_task(runCommand())
		return -1

	#decorators for containers
	@classmethod
	def command(cls,commandname,complete=[]):
		'''
		Add function as a command `commandname` with argument suggestion `complete`
		`complete` may either be a list or a function returning a list and a number
		that specifies where to start the suggestion from
		'''
		def wrapper(func):
			cls._commands[commandname] = func
			if complete:
				cls._commandComplete[commandname] = complete
				
		return wrapper

class EscapeOverlay(OverlayBase):
	'''Overlay for redirecting input after \ is pressed'''
	replace = False
	def __init__(self,parent,scroll):
		super(EscapeOverlay, self).__init__(parent)
		addTab		= override(staticize(scroll.append,'\t'),-1,nodoc=True)
		addNewLine	= override(staticize(scroll.append,'\n'),-1,nodoc=True)
		addSlash	= override(staticize(scroll.append,'\\'),-1,nodoc=True)
		self._keys.update({
			-1:		quitlambda
			,9:		addTab
			,10:	addNewLine
			,ord('n'):	addNewLine
			,ord('\\'):	addSlash
			,ord('t'):	addTab
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

class Messages:
	'''Container object for message objects'''
	_INDENT = "    "
	def __init__(self,parent):
		self.clear()
		self.parent = parent
		
	def clear(self):
		'''Clear all lines and messages'''
		self.canselect = True
		self.allMessages = []	#contains every message as 4-lists of Coloring
								#objects, arg tuples, message length since last
								#break, and message ID
		self.lines = []			#contains every line currently or recently
								#involved in drawing
		self.msgID = 0			#next message id
		#selectors
		self.selector = 0		#selected message
		self.startheight = 0	#to calculate which message we're drawing from
								#so that selected can be seen relative to it
		self.linesup = 0		#start drawing from this lines index (reversed)
		self.distance = 0		#number of lines down from startheight's message
		self.innerheight = 0	#inner message height, to start drawing message
								#lines late
		#lazy storage
		self.lazyColor	= [-1,-1] #latest/earliest messages to recolor
		self.lazyFilter = [-1,-1] #latest/earliest messages to refilter

		#deletion lambdas
		self.lazyDelete = []

	def stopSelect(self):
		'''Stop selecting'''
		if self.selector:
			self.selector = 0
			self.linesup = 0
			self.innerheight = 0
			self.distance = 0
			self.startheight = 0
			#rebuild lines
			needRecolor = self.lazyColor[0] != -1
			if self.lazyFilter[0] != -1 or needRecolor:
				self.redolines(recolor = needRecolor)
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
		selftraverse,linetraverse = -self.linesup-1,-2
		lenself, lenlines = -len(self.lines),-len(lines)
		msgno = -self.startheight-1

		thismsg = self.allMessages[msgno][2] - self.innerheight
		#traverse list of lines
		while selftraverse >= lenself and linetraverse >= lenlines:
			reverse = (msgno == -self.selector) and SELECT_AND_MOVE or ""
			lines[linetraverse] = reverse + self.lines[selftraverse]

			selftraverse -= 1
			linetraverse -= 1
			thismsg -= 1
			while not thismsg:
				msgno -= 1
				if msgno >= -len(self.allMessages):
					thismsg = self.allMessages[msgno][2]
				else:
					break

	def applyLazies(self,select,direction):
		'''
		Generator that yields on application of lazy iterators to mesages
		The value yielded corresponds to the kind of lazy operation performed
		0:	deletion
		1:	filtering
		2:	coloring
		'''
		message = self.allMessages[-select]
		#next message index is out of bounds
		nextOOB = (select+direction >= len(self.allMessages)) \
			or not (select+direction)
		#next message if out of bounds to apply lazies on
		nextFilter = nextOOB and -1 or self.allMessages[-select-direction][3]

		#test all lazy deleters
		for test,result in self.lazyDelete:
			if test(message,result):
				del self.allMessages[-select]
				if message[3] == self.lazyFilter[direction == 1]:
					self.lazyFilter[direction == 1] = nextFilter
				if message[3] == self.lazyColor[direction == 1]:
					self.lazyColor[direction == 1] = nextFilter
				return 0

		#lazy filters
		if message[3] == self.lazyFilter[direction == 1]:
			#use a dummy length (0/1) to signal that the message should be drawn
			message[2] = ((message[1] is None) or \
				not self.parent.filterMessage(*message[1]))
			self.lazyFilter[direction == 1] = nextFilter

		if message[3] == self.lazyColor[direction == 1]:
			#ignore system
			if (message[1] is not None):
				message[0].clear()
				self.parent.colorizeMessage(message[0],*message[1])
			self.lazyColor[direction == 1] = nextFilter

		return message[2]
		
	def scrollup(self):
		windowHeight = self.parent.parent.y-1
		#scroll within a message if possible, and exit
		if self.selector and \
		self.allMessages[-self.selector][2] - windowHeight > self.innerheight:
			self.linesup += 1
			self.innerheight += 1
			return -1

		select = self.selector+1
		addlines = 0
		while not addlines and select <= len(self.allMessages):
			addlines = self.applyLazies(select,1)
			select += 1

		#if the message just had its length calculated as 1, this barely works
		offscreen = (self.distance + addlines - windowHeight)
		#next message out of bounds and select refers to an actual message
		if self.linesup + self.distance + addlines > len(self.lines) and \
		select-1 <= len(self.allMessages):
			message = self.allMessages[-select+1]
			#break the message, then add at the beginning
			new = message[0].breaklines(self.parent.parent.x,self._INDENT)
			message[2] = len(new)
			#append or prepend
			self.lines[0:0] = new
			offscreen += message[2]-addlines
			addlines = message[2]

		self.distance += addlines

		#can only make sense when the instance properly handles variables
		#so checking validity is futile
		if offscreen > 0:
			#get a delta from the top, just in case we aren't there already
			self.linesup += offscreen
			canscroll = self.allMessages[-self.startheight-1][2] - self.innerheight
			#scroll through messages if needed
			if offscreen - canscroll >= 0:
				while offscreen - canscroll >= 0:
					offscreen -= canscroll
					self.startheight += 1
					canscroll = self.allMessages[-self.startheight-1][2]
				self.innerheight = offscreen
			else:
				self.innerheight += offscreen

			self.distance = windowHeight

		self.selector = select-1
#		self.dump()

		return addlines

	def scrolldown(self):
		if not self.selector: return 0
		windowHeight = self.parent.parent.y-1
		#scroll within a message if possible, and exit
		if self.selector == self.startheight+1 and \
		self.innerheight > 0:	#there is at least one hidden line
			self.linesup -= 1
			self.innerheight -= 1 
			return -1

		select = self.selector-1
		addlines = 0
		while not addlines and select <= len(self.allMessages):
			addlines = self.applyLazies(select,-1)
			select -= 1
		select += 1

		lastLines = self.allMessages[-self.selector][2]
		nextPos = self.linesup + self.distance - lastLines - addlines
		#append message lines if necessary
		if nextPos < 0 and select > 0:
			message = self.allMessages[-select]
			#break the message, then add at the end
			new = message[0].breaklines(self.parent.parent.x,self._INDENT)
			addlines = len(new)
			message[2] = addlines
			self.lines.extend(new)
			#to cancel out with distance in the else statement below
			self.innerheight = -max(addlines,addlines-windowHeight)

		#fix the last line to show all of the message
		if select == self.startheight+1:
			self.distance = min(windowHeight,addlines)
			newheight = max(0,addlines - windowHeight)
			#this newheight will hide fewer lines; it's less than innerheight
			#the delta, if there are still lines left
			self.linesup -= self.innerheight - newheight
			self.innerheight = newheight
			#startheight is off by one
			self.startheight = select-1
		#scroll down to the next message
		elif select and self.selector == self.startheight+1:
			self.distance = min(windowHeight,addlines)
			self.linesup -= min(windowHeight, self.innerheight + self.distance)

			self.innerheight = max(0,addlines - windowHeight)
			self.startheight = select-1
		else:
			self.distance -= lastLines

		self.selector = select
		if not self.selector:
			self.distance = 0
			self.linesup = 0
			self.startheight = 0
			self.innerheight = 0

#		self.dump()
		return addlines
			
	def append(self,message,args = None):
		'''Add new message to the end of allMessages and lines'''
		#undisplayed messages have length zero
		msg = [message,args,0,self.msgID]
		self.msgID += 1
		self.allMessages.append(msg)
		
		#don't bother drawing; filter
		if (args is not None) and self.parent.filterMessage(*args):
			self.selector += (self.selector > 0)
			self.startheight += (self.startheight > 0)
			return msg[-1]

		new = message.breaklines(self.parent.parent.x,self._INDENT)
		msg[2] = len(new)
		#adjust selector iterators
		if self.selector:
			self.selector += 1
			#scrolled up too far to see
			if self.startheight or \
			msg[2] + self.distance > (self.parent.parent.y-1):
				self.startheight += 1
				self.lazyFilter[0]	= msg[3]
				self.lazyColor[0]	= msg[3]
				return msg[-1]
			self.distance += msg[2]
		#add lines if and only if necessary
		self.lines.extend(new)

		return msg[-1]

	def prepend(self,message,args = None):
		'''Prepend new message. Use msgPrepend instead'''
		#run filters early so that the message can be selected up to properly
		dummyLength = not self.parent.filterMessage(*args) if args is not None else 1
		msg = [message, args, dummyLength, self.msgID]
		self.msgID += 1
		self.allMessages.insert(0,msg)
		#lazyfilter checking ensures that prepending to lines is valid
		if dummyLength and self.lazyFilter[1] == -1:
			new = message.breaklines(self.parent.parent.x,self._INDENT)
			self.lines[0:0] = new
			msg[2] = len(new)

		return msg[-1]

	def delete(self,result,test=lambda x,y: x[3] == y):
		'''Delete message from value result and callable test'''
		if not callable(test):
			raise TypeError("delete requires callable")

		msgno = self.startheight+1
		height = self.allMessages[-msgno][2]-self.innerheight

		while height <= self.parent.parent.y-1:
			if (test(self.allMessages[-msgno],result)):
				del self.allMessages[-msgno]
				self.redolines()
				return
			msgno += 1
			height += self.allMessages[-msgno][2]

		self.lazyDelete.append(test,result)

	def getMessageFromPosition(self,x,y):
		'''Get the message and depth into the message at position x,y'''
		#we always draw "upward," so 0 being the bottom is more useful
		y = (self.parent.parent.y-1) - y
		if y <= 0: return "",-1

		msgno = self.startheight+1		#we start drawing from this message
		msg = self.allMessages[-msgno]
		height = msg[2] - self.innerheight	#visible lines shown 

		#find message until we exceed the height
		while height < y:
			#advance the message number, or return if we go too far
			msgno += 1
			if msgno > len(self.allMessages):
				return "",-1
			msg = self.allMessages[-msgno]
			height += msg[2]

		#line depth into the message
		depth = height - y
		pos = 0

		#adjust the position
		for i in range(depth):
			#only subtract from the length of the previous line if it's not the first one
			pos += numdrawing(self.lines[i-height]) - (i and len(self._INDENT))
		if x >= collen(self._INDENT) or not depth:
			#try to get a slice up to the position 'x'
			pos += max(0,numdrawing(self.lines[depth-height],x) - len(self._INDENT))
			
		return msg,pos

	def scrollToMessage(self,messageIndex):
		'''
		Directly set selector and startheight and redolines.
		Redraw necessary afterward.
		'''
		self.selector = messageIndex
		#TODO maybe try to draw up, then back down if too few lines to fill up the top?
		self.startheight = messageIndex-1
		self.redolines()

	def scrollToTop(self):
		top = len(self.allMessages)
		if self.selector == top: return -1
		self.scrollToMessage(top)

	def iterateWith(self,callback):
		'''
		Returns an iterator that yields when the callback is true.
		Callback is called with arguments passed into append (or msgPost...)
		'''
		select = 1
		while select <= len(self.allMessages):
			message = self.allMessages[-select]
			#ignore system messages
			if message[1] and callback(*message[1]):
				yield message[0],select
			select += 1

	#REAPPLY METHODS-----------------------------------------------------------
	def redolines(self, width = None, height = None, recolor = False):
		'''
		Redo lines, if current lines does not represent the unfiltered messages
		or if the width has changed
		'''
		#search for a fitting message to set as selector
		i = self.allMessages[-self.selector]
		while self.selector > 0 and ((i[1] is not None) and \
		self.parent.filterMessage(*i[1])):
			self.selector -= 1
			i = self.allMessages[-self.selector]

		#a new start height must be decided
		if width or height or self.selector <= self.startheight:
			self.startheight = max(0,self.selector-1)
		if width is None: width = self.parent.parent.x
		if height is None: height = self.parent.parent.y
		#must change lazyColor bounds 
		if self.startheight: recolor = True	

		startMessage = self.allMessages[-self.startheight-1]
		if recolor and startMessage[1] is not None:	#don't decolor system messages
			startMessage[0].clear()
			self.parent.colorizeMessage(startMessage[0],*startMessage[1])
		newlines = startMessage[0].breaklines(width,self._INDENT)
		startMessage[2] = len(newlines)

		self.innerheight = max(0,startMessage[2] - height)
		#distance only if we're still selecting
		self.distance = min(height,self.selector and startMessage[2])
		self.linesup = self.innerheight

		msgno, lineno = self.startheight+2, self.distance
	
		self.lazyFilter[0]	= self.allMessages[-self.startheight][3] \
								if self.startheight	else -1
		
		while lineno < height and msgno <= len(self.allMessages):
			i = self.allMessages[-msgno]
			notSystem = i[1] is not None
			#check if the message should be drawn
			if recolor and notSystem:	#don't decolor system messages
				i[0].clear()
				self.parent.colorizeMessage(i[0],*i[1])
			#re-filter message
			if notSystem and self.parent.filterMessage(*i[1]):
				i[2] = 0
				msgno += 1
				continue
			#break and add lines
			new = i[0].breaklines(width,self._INDENT)
			newlines[0:0] = new
			i[2] = len(new)
			lineno += i[2]
			msgno += 1

		self.lazyFilter[1]	= -1	if msgno-1 == len(self.allMessages) \
									else self.allMessages[-msgno][3]
		if recolor:
			#duplicate the lazy bounds
			self.lazyColor = list(self.lazyFilter)

#		self.dump()
		self.lines = newlines
		self.canselect = True

	def recolorlines(self):
		'''Re-apply parent's colorizeMessage and redraw all visible lines'''
		width = self.parent.parent.x
		height = self.parent.parent.y-1
		
		startMessage = self.allMessages[-self.startheight-1]
		if startMessage[1] is not None:	#don't decolor system messages
			startMessage[0].clear()
			self.parent.colorizeMessage(startMessage[0],*startMessage[1])

		newlines = startMessage[0].breaklines(width,self._INDENT)
		if len(newlines) != startMessage[2]:
			raise DisplayException("recolorlines called before redolines")

		self.lazyColor[0] = self.allMessages[-self.startheight][3] \
								if self.startheight	else -1

		lineno,msgno = startMessage[2]-self.innerheight,self.startheight+2
		while lineno < height and msgno <= len(self.allMessages):
			i = self.allMessages[-msgno]
			if i[1] is not None:	#don't decolor system messages
				i[0].clear()
				self.parent.colorizeMessage(i[0],*i[1])
			if i[2]: #unfiltered (non zero lines)
				new = i[0].breaklines(width,self._INDENT)
				if len(new) != i[2]:
					raise DisplayException("recolorlines called before redolines")
				newlines[0:0] = new
				lineno += i[2]
			msgno += 1

		self.lazyColor[1] = -1	if msgno-1 == len(self.allMessages) \
									else self.allMessages[-msgno][3]

		self.lines = newlines
		self.linesup = self.innerheight

class ChatOverlay(TextOverlay):
	'''
	Overlay that can push and select messages, and has an input box.
	Optionally pushes time messages every 10 minutes and refreshes 
	blurbs every few seconds
	'''
	replace = True
	_monitors = {}
	def __init__(self,parent,pushtimes = True):
		super(ChatOverlay, self).__init__(parent)
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
			self.parent._updateinput()
			return 1

	def add(self):
		'''Start timeloop and add overlay'''
		super(ChatOverlay,self).add()
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
			self._pushTask.cancel()
		if not self.index:
			self.parent.active = False
		super(ChatOverlay,self).remove()

	@asyncio.coroutine
	def resize(self,newx,newy):
		'''Resize scrollable and maybe draw lines again if width changed'''
		yield from super(ChatOverlay,self).resize(newx,newy)
		self.messages.redolines(newx,newy)

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
		allMessages without drawing to lines. Arguments are left generic so
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
		self.parent.soundBell()
		self.messages.canselect = 0

	def selectup(self):
		'''Select message up'''
		if not self.messages.canselect: return 1
		#go up the number of lines of the "next" selected message
		upmsg = self.messages.scrollup()
		#but only if there is a next message
		if not upmsg: self._maxselect()
		return 1

	def selectdown(self):
		'''Select message down'''
		if not self.messages.canselect: return 1
		#go down the number of lines of the currently selected message
		self.messages.scrolldown()
		if not self.messages.selector:
			#move the cursor back
			self.parent._updateinput()
		return 1

	def selectmax(self):
		'''Select top message'''
		if not self.messages.canselect: return 1
		if self.messages.scrollToTop() == -1:
			self._maxselect()
		return 1

	def redolines(self, recolor = False):
		self.messages.redolines(recolor = recolor)
		self.parent.scheduleDisplay()
		
	def recolorlines(self):
		self.messages.recolorlines()
		self.parent.scheduleDisplay()

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

class _MessageScrollOverlay(DisplayOverlay):
	'''
	DisplayOverlay with the added capabilities to display messages in a
	LazyIterList and to scroll a ChatOverlay to the message index of such
	a message. Do not directly create these; use addMessageScroller.
	'''
	def __init__(self,chatOverlay,lazyList,msgEarly,msgLate):
		self.lazyList = lazyList

		self.msgno = lazyList[0][1]
		self.msgEarly = msgEarly
		self.msgLate = msgLate
		
		super(_MessageScrollOverlay,self).__init__(chatOverlay.parent,
			lazyList[0][0], chatOverlay.messages._INDENT)
		scrollDown	= lambda: self.nextMessage(-1)
		scrollUp	= lambda: self.nextMessage(1)
		scrollTo 	= lambda: chatOverlay.messages.scrollToMessage(self.msgno) \
			or -1
		self._keys.update({
			9:			scrollTo
			,10:		scrollTo
			,ord('N'):	scrollDown
			,ord('n'):	scrollUp
		})
		self._altkeys.update({
			ord('j'):	scrollDown
			,ord('k'):	scrollUp
		})

	def nextMessage(self,step):
		attempt = self.lazyList.step(step)
		if attempt:
			self.changeDisplay(attempt[0])
			self.msgno = attempt[1]
		elif step == 1:
			self.parent.newBlurb(self.msgEarly)
		elif step == -1:
			self.parent.newBlurb(self.msgLate)

def addMessageScroller(chatOverlay,callback,msgEmpty,msgEarly,msgLate):
	'''
	Add a message scroller for a particular callback.
	This wraps Messages.iterateWith with a LazyIterList, spawns an instance of
	_MessageScrollOverlay, and adds it to the same parent as chatOverlay.
	Error blurbs are printed to chatOverlay's parent: msgEmpty for an exhausted
	iterator, msgEarly for when no earlier messages matching the callback are
	found, and msgLate for the same situation with later messages.
	'''
	try:
		lazyList = LazyIterList(chatOverlay.messages.iterateWith(callback))
	except TypeError:
		chatOverlay.parent.newBlurb(msgEmpty)
		return

	ret = _MessageScrollOverlay(chatOverlay,lazyList,msgEarly,msgLate)
	ret.add()
	return ret

#INPUTMUX CLASS-----------------------------------------------------------------
class InputMux:
	'''
	Abstraction for a set of adjustable values to display with a ListOverlay.
	Comes pre-built with drawing for each kind of value.
	'''
	def __init__(self):
		self._ordering = []
		self.indices = {}
		self.context = None
		self.parent = None

	def add(self,parent,context):
		'''Add the muxer with ChatangoOverlay `parent`'''
		self.context = context
		self.parent = parent
		overlay = ListOverlay(parent
			,[self.indices[i]._doc for i in self._ordering]
			,self._drawing)
		selectSub = lambda me: self.indices[self._ordering[overlay.it]]._select()
		selectSub.__doc__ = "Change value"
		overlay._keys.update({
			9:			selectSub
			,10:		selectSub
			,ord(' '):	selectSub
		})
		overlay.add()

	def _drawing(self,me,string,i):
		'''Defer to the _ListEl's local drawer'''
		element = self.indices[self._ordering[i]]
		element._drawer(self,element._getter(self.context),string)

	class _ListEl:
		'''
		Decorator to create an input field with a certain data type.
		dataType can be one of "str", "color", "enum", or "bool"
		The __init__ is akin to a `@property` decorator: as a getter;
		subsequent setters and drawers can be added from the return value
		(bound to func.__name__); i.e. `@func.setter...`

		func should have signature:
			(context:	the context as supplied by the InputMux)
		The name of the field in the list will be derived from func.__doc__
		'''
		def __init__(self,parent,dataType,func):
			self.name = func.__name__
			if parent.indices.get(self.name):
				raise TypeError("Cannot implement element %s more than once"%\
					self.name)
			#bind parent names
			self.parent = parent
			self.parent.indices[self.name] = self
			self.parent._ordering.append(self.name)
			self._doc = func.__doc__
			self._type = dataType
			#default drawer
			if self._type == "color":
				self._drawer = self.colorDrawer
			elif self._type == "str":
				self._drawer = self.stringDrawer
			elif self._type == "enum":
				self._drawer = self.enumDrawer
			elif self._type == "bool":
				self._drawer = self.boolDrawer
			else:	#invalid type
				raise TypeError("input type %s not recognized"%self._type)

			self._getter = func
			self._setter = None

		def setter(self,func):
			'''Decorator to set setter. Setters should have the signature:
				(context:	the context supplied by the InputMux
				,value:		the new value after input)
			'''
			self._setter = func
			return self
		def drawer(self,func):
			'''
			Decorator to set drawer. Drawers should have the signature:
				(mux:		the InputMux instance the _ListEl is a part of
				,value:		the value of the element obtained by the getter
				,coloring:	the row's Coloring object)
			'''
			self._drawer = func
			return self

		def _select(self):
			'''Open input overlay to modify value'''
			furtherInput = None
			if self._type == "color":
				furtherInput = ColorOverlay(self.parent.parent
					#callback
					,lambda ret: self._setter(self.parent.context,ret) or -1
					,self._getter(self.parent.context))			#initial color
			elif self._type == "str":
				furtherInput = InputOverlay(self.parent.parent
					,self._doc								#input window text
					,lambda ret: self._setter(self.parent.context,ret)) #callback
			elif self._type == "enum":
				li,index = self._getter(self.parent.context)
				furtherInput = ListOverlay(self.parent.parent
					,li)		#enum entries
				furtherInput.it = index
				setCallback = lambda me: self._setter(self.parent.context,me.it) or -1
				furtherInput.addKeys(
					{'tab':		setCallback
					,'enter':	setCallback
					,' ':		setCallback
				})
			elif self._type == "bool":
				self._setter(self.parent.context,
					not self._getter(self.parent.context))	#toggle
				return
			furtherInput.add()
			
		@staticmethod
		def colorDrawer(mux,value,coloring):
			'''Default color drawer'''
			coloring.insertColor(-1,mux.parent.get256color(value))
			coloring.effectRange(-1,0,0)
		@staticmethod
		def stringDrawer(mux,value,coloring):
			'''Default string drawer'''
			val = str(value)
			coloring.addIndicator(val,rawNum(7))	#yellow
		@classmethod
		def enumDrawer(cls,mux,value,coloring):
			'''Default enum drawer'''
			#dereference and run string drawer
			cls.stringDrawer(mux,value[0][value[1]],coloring)
		@staticmethod
		def boolDrawer(mux,value,coloring):
			'''Default bool drawer'''
			coloring.addIndicator(value and "y" or "n", value and rawNum(6) \
				or rawNum(5))

	def listel(self,dataType):
		'''
		Frontend decorator to create a _ListEl. Abstracts away the need to
		supply `parent` and  transforms the decorator to be of the form
		@listel(dataType) (=> _ListEl(self,dataType,__decorated_func__))
		'''
		return staticize(self._ListEl,self,dataType)

#OVERLAY MANAGER----------------------------------------------------------------
class Main:
	'''Main class; handles all IO and defers to overlays'''
	last = 0
	_afterDone = []
	def __init__(self,loop=None):
		self.loop = asyncio.get_event_loop() if loop is None else loop
		if not hasattr(loop,"create_future"):
			setattr(loop,"create_future",lambda: asyncio.Future(loop=loop))
		self._displaybuffer = sys.stdout
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

	#Display Methods------------------------------------------------------------
	def soundBell(self):
		'''Sound console bell.'''
		self._displaybuffer.write('\a')

	@asyncio.coroutine
	def display(self):
		'''Display backend'''
		if not (self.active and self.candisplay): return
		#justify number of lines
		lines = ["" for i in range(self.y)]
		#start with the last "replacing" overlay, then all overlays afterward
		try:
			for start in range(self._lastReplace,len(self._ins)):
				yield from self._ins[start](lines)
		except SizeException:
			self.candisplay = 0
			return
		self._displaybuffer.write(DISPLAY_INIT)
		#draw each line in lines, deleting the rest of the garbage on the line
		for i in lines:
			self._displaybuffer.write(i+"\x1b[K\n\r")
		self._displaybuffer.write(RETURN_CURSOR)

	def scheduleDisplay(self):
		self.loop.create_task(self.display())

	def _updateinput(self):
		'''Input display backend'''
		if not (self.active and self.candisplay): return
		if not self._scrolls: return	#no textoverlays added
		string = format(self._scrolls[-1])
		self._displaybuffer.write(SINGLE_LINE % (self.y+1,string))

	def _printblurb(self,blurb,time):
		'''Blurb display backend'''
		if not (self.active and self.candisplay): return
		#try to queue a blurb	
		if blurb == "": pass
		elif isinstance(blurb,Coloring):
			self._blurbQueue = blurb.breaklines(self.x)
		else:
			self._blurbQueue = Coloring(blurb).breaklines(self.x)
		#holding a message?
		if self.last < 0: return
		#next blurb is either a pop from the last message or nothing
		if len(self._blurbQueue):
			blurb = self._blurbQueue.pop(0)
		else:
			blurb = ""
		self.last = time
		#move cursor, clear row, print blurb, and return cursor
		self._displaybuffer.write(SINGLE_LINE % (self.y+2,blurb))

	def updateinfo(self,right=None,left=None):
		'''Update screen bottom'''
		if not (self.active and self.candisplay): return
		templeft = str(left or self._bottom_edges[0])
		tempright = str(right or self._bottom_edges[1])
		room = self.x - collen(templeft) - collen(tempright)
		#in the case of an update not invoked by internals
		if room < 1 and (right or left):
			raise SizeException("updateinfo failed: right and left overlap")

		self._bottom_edges[0] = templeft
		self._bottom_edges[1] = tempright

		self._displaybuffer.write(SINGLE_LINE % (self.y+3, "\x1b[7m" + \
			templeft + (" "*room) + tempright + "\x1b[m"))

	def redrawAll(self):
		'''Force redraw'''
		self.scheduleDisplay()
		self.newBlurb()
		self.updateinfo()
		self._updateinput()

	@asyncio.coroutine
	def resize(self):
		'''Resize the GUI'''
		newy, newx	 = self._screen.getmaxyx()
		#some terminals don't like drawing the last column
		if os.getenv("TERM") == "xterm": newx -= 1
		#magic number, but who cares; lines for text, blurbs, and reverse info
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
		yield from self.display()
		self._updateinput()

	#Blurb Drawing Frontends----------------------------------------------------
	def newBlurb(self,message = ""):
		'''Add blurb. Use in conjunction with ChatOverlay to erase'''
		self._printblurb(message,self.loop.time())

	def holdBlurb(self,message):
		'''Hold blurb. Sets self.last to -1, making newBlurb not draw'''
		self._printblurb(message,-1)

	def releaseBlurb(self):
		'''
		Release blurb. Sets self.last to a valid time, making newBlurb
		start drawing again.
		'''
		self.last = self.loop.time()
		self._printblurb("",self.last)

	#Overlay Backends-----------------------------------------------------------
	def addOverlay(self,new):
		'''Add overlay'''
		if not isinstance(new,OverlayBase): return
		new.index = len(self._ins)
		self._ins.append(new)
		if new.replace: self._lastReplace = new.index
		#display is not strictly called beforehand, so better safe than sorry
		self.scheduleDisplay()

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
		self.scheduleDisplay()

	def addScrollable(self,newScroll):
		'''Add a new scrollable and return it'''
		newScroll._setIndex(len(self._scrolls))
		self._scrolls.append(newScroll)
		self._updateinput()
		return newScroll

	def popScrollable(self,which):
		'''Pop a scrollable added from addScrollable'''
		del self._scrolls[which._index]
		self._updateinput()

	#Overlay Frontends----------------------------------------------------------
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

	#Loop Coroutines------------------------------------------------------------
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
		sys.stdout = open("/tmp/client.log","a+",buffering=1)
		if sys.stderr.isatty(): sys.stderr = sys.stdout
		#curses input setup
		self._screen = curses.initscr()		#init screen
		curses.noecho(); curses.cbreak(); self._screen.keypad(1) #setup curses
		self._screen.nodelay(1)	#don't wait for enter to get input
		self._screen.getch() #the first getch clears the screen

		#escape has delay, not that this matters since I use tmux frequently
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
				except Exception as exc:
					print("Error occurred during shutdown:")
					print(traceback.format_exc(),"\n")
			#return to sane mode
			curses.echo(); curses.nocbreak(); self._screen.keypad(0)
			curses.endwin()
			sys.stdout.close() #close the temporary buffer set up
			sys.stdout = self._displaybuffer #reconfigure output
			
			self.loop.remove_signal_handler(SIGINT)
			self.loop.remove_signal_handler(SIGTSTP)
			for i in self._afterDone:
				yield from i
			self.exited.set()

	def start(self):
		return self.loop.create_task(self.run())

	def stop(self):
		curses.ungetch(27)
		self.active = False
		
	#Miscellaneous Frontends----------------------------------------------------
	def toggle256(self,state):
		'''Turn the mode to 256 colors, and if undefined, define colors'''
		self._two56 = state
		if state and not hasattr(self,"_two56start"): #not defined on startup
			self._two56start = numDefinedColors()
			def256colors()

	def toggleMouse(self,state):
		'''Turn the mouse on or off'''
		return curses.mousemask(state and _MOUSE_MASK)

	def get256color(self,color,green=None,blue=None):
		'''
		Convert a hex string to 256 color variant or get
		color as a pre-caluclated number from `color`
		Returns rawNum(0) if not running in 256 color mode
		'''
		if not self._two56: return rawNum(0)

		if isinstance(color,int):
			return self._two56start + color
		elif isinstance(color,float):
			raise TypeError("cannot call get256color with float")
			
		if color is not None and green is not None and blue is not None:
			color = (color,green,blue) 
		elif not color:			#empty string
			return rawNum(0)
		
		try:
			if isinstance(color,str):
				partsLen = len(color)//3
				in216 = [int(int(color[i*partsLen:(i+1)*partsLen],16)*5/\
					(16**partsLen)) for i in range(3)]
			else:
				in216 = [int(color[i]*5/255) for i in range(3)]
				
			#too white or too black
			if sum(in216) < 2 or sum(in216) > 34:
				raise AttributeError
			return self._two56start + 16 + sum(map(lambda x,y: x*y,in216,[36,6,1]))
		except (AttributeError,TypeError):
			return rawNum(0)
	
	@classmethod
	def onDone(cls,func,*args):
		'''
		Add function or prepared coroutine to be run after the Main 
		instance has shut down
		'''
		if asyncio.iscoroutinefunction(func):
			raise TypeError("Coroutine, not coroutine object, passed into onDone")
		elif not asyncio.iscoroutine(func):
			func = asyncio.coroutine(func)(*args)
		cls._afterDone.append(func)
		return func

@CommandOverlay.command("help")
def listcommands(parent,*args):
	'''Display a list of the defined commands and their docstrings'''
	def select(self):
		new = CommandOverlay(parent)
		new.text.append(self.list[self.it])
		self.swap(new)

	commandsList = ListOverlay(parent,list(CommandOverlay._commands))
	commandsList.addKeys({
		"enter":select
	})
	return commandsList

@CommandOverlay.command("q")
def quit(parent,*args):
	parent.stop()
