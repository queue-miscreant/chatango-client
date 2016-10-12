#!/usr/bin/env python3
#client.overlay.py
'''Client module with single-byte curses input uses a
system of overlays, pulling input from the topmost
one. Output is done not with curses display, but various
different stdout printing calls.'''
#TODO	invoke promises on inputOverlay
#TODO	rewrite docstrings
#TODO	dbmsg that turns off cbreak mode and back on
try:
	import curses
except ImportError:
	raise ImportError("ERROR WHILE IMPORTING CURSES, is this running on Windows cmd?")
import sys
from os import environ
if not (sys.stdin.isatty() and sys.stdout.isatty()): #check if terminal
	raise IOError("This script is not intended to be piped")
#escape has delay typically
environ.setdefault('ESCDELAY', '25')
#stupid? yes.
import time
from threading import Thread
from .display import *

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

#KEYS---------------------------------------------------------------------------
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
del i

class KeyException(Exception):
	'''Exception for keys-related errors in client.display'''

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

#decorators for containers
def colorize(func):
	'''Add function as a colorizer.'''
	_colorizers.append(func)
def filter(func):
	'''Add function as a filter.'''
	_filters.append(func)
def command(commandname):
	'''Add function as a command `commandname`'''
	def wrapper(func):
		_commands[commandname] = func
	return wrapper

#OVERLAY HELPERS------------------------------------------------------------------
CHAR_RETURN_CURSOR = '\x1b[u\n\x1b[A'
CHAR_COMMAND = "`"
tabber(CHAR_COMMAND,_commands)
		
def centered(string,width,isselected=False):
	'''Center (and select) some text'''
	pre = string.rjust((width+len(string))//2).ljust(width)
	if isselected: pre = SELECTED(pre)
	return pre

class box:
	'''Namespace-esque thing for drawing boxes line by line'''
	CHAR_HSPACE = "─"
	CHAR_VSPACE = "│"
	CHAR_TOPL = "┌"
	CHAR_TOPR = "┐"
	CHAR_BTML = "└"
	CHAR_BTMR = "┘"
	width = 0
	noform = lambda x: box.CHAR_VSPACE + x + box.CHAR_VSPACE
	def format(left,string,right,justchar = ' '):
		'''Format and justify part of box'''
		return '%s%s%s' % (left,box.just(string,justchar),right)
	def just(string,justchar = ' '):
		'''Justify string by column width'''
		return '%s%s' % (string,justchar*(box.width-2-strlen(string)))
	def part(fmt = '') :
		'''Format with vertical spaces'''
		return box.format(box.CHAR_VSPACE,fmt,box.CHAR_VSPACE)
	def top(fmt = ''):
		'''Format with box tops'''
		return box.format(box.CHAR_TOPL,fmt,box.CHAR_TOPR,box.CHAR_HSPACE)
	def bottom(fmt = ''):
		'''Format with box bottoms'''
		return box.format(box.CHAR_BTML,fmt,box.CHAR_BTMR,box.CHAR_HSPACE)

class history:
	'''Container class for historical entries, a la an actual shell'''
	def __init__(self):
		self.history = []
		self._selhis = 0
		self.temp = ''
	def nexthist(self):
		'''Next in history (less recent)'''
		if self.history:
			self._selhis += (self._selhis < (len(self.history)))
			return self.history[-self._selhis]
		return ''
	def prevhist(self):
		'''Back in history (more recent)'''
		if self.history:
			self._selhis -= (self._selhis > 0)
			#the next element or an empty string
			return self._selhis and self.history[-self._selhis] or ""
		return ''
	def append(self,new):
		'''Add new entry in history'''
		self.history.append(new)
		self.history = self.history[-50:]
		self._selhis = 0

#DISPLAY/OVERLAY CLASSES----------------------------------------------------------
SELECT_AND_MOVE = CHAR_CURSOR + getEffect('reverse')[0]
SELECT = getEffect('reverse')[0]

class DisplayException(Exception):
	'''Exception for display-related errors in client.display'''

def _moveCursor(row = 0):
	print("\x1b[%d;f" % row,end=CLEAR_FORMATTING)
def soundBell():
	'''Raise console bell'''
	print('\a',end="")

#please don't need these
quitlambda = lambda x: -1
def staticize(func,*args):
	def ret(garbage):			#garbage would be a list of characters
		return func(*args)
	ret.__doc__ = func.__doc__	#preserve documentation text
	return ret

class overlayBase:
	'''An overlay is a class that redirects input and modifies a list of (output) strings'''
	def __init__(self,parent):
		self.parent = parent		#parent
		self.index = None			#index in the stack
		self._keys =	{27:	self._callalt
				,curses.KEY_RESIZE:	staticize(parent.resize)}
		self._altkeys =	 {None:	lambda: -1}
	def __dir__(self):
		'''Get a list of keynames and their documentation'''
		ret = []
		for i,j in _VALID_KEYNAMES.items():
			#ignore named characters and escape, they're not verbose
			if i in ('^[','^i','^j',chr(127)): continue	
			if j in self._keys:
				ret.append('%s: %s' % (i,self._keys[j].__doc__))
			if j in self._altkeys:
				ret.append('a-%s: %s' % (i,self._altkeys[j].__doc__))
		ret.sort()
		return ret
	def __call__(self,lines):
		'''Overridable function. Modify lines by address (i.e lines[value]) to display from main'''
		pass
	def _callalt(self,chars):
		'''Call a method from _altkeys.'''
		return chars[0] in self._altkeys and self._altkeys[chars[0]]()
	def _post(self):
		'''Run after a keypress if the associated function returns boolean false\n'''+\
		'''If either the keypress or this return boolean true, the overlay's '''+\
		'''parent redraws'''
		return 1
	def runkey(self,chars):
		'''Call the overlay. This expects a single argument: a list of numbers '''+\
		'''terminated by -1'''
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
		'''Nice method to add keys after instantiation. Support for '''+\
		'''a- (alt keys), or curses keynames.'''
		for i,j in newFunctions.items():
			if isinstance(i,str):
				if not i.lower().find('a-'):
					i = i[2:]
					if i in _VALID_KEYNAMES:
						i = _VALID_KEYNAMES[i]
						if areMethods:
							self._altkeys[i] = j
						else:
							self._altkeys[i] = lambda: j(self)
						continue
					else: raise KeyException('key alt-%s invalid'%i)
				else:
					try:
						i = _VALID_KEYNAMES[i]
					except: raise KeyException('key %s not defined'%i)
			if areMethods:
				self._keys[i] = staticize(j)
			else:
				self._keys[i] = staticize(j,self)

class textOverlay(overlayBase):
	'''Virtual overlay with text input (at bottom of screen)'''
	def __init__(self,parent = None):
		overlayBase.__init__(self,parent)
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
		'''Safer version that takes out invalid ASCII (chars above 256) that might get pushed by curses'''
		return self.text.append(bytes([i for i in chars if i<256]).decode())
	def resize(self,newx,newy):
		'''Adjust scrollable on resize'''
		self.text.setwidth(newx)
	def remove(self):
		'''Don't forget to pop scrollable'''
		super().remove()
		self.parent.popScrollable(self.text)
	def controlhistory(self,history,scroll):
		'''Add key definitions for standard controls for history `history` '''+\
		'''and scrollable `scroll`'''
		nexthist = lambda x: scroll.setstr(history.nexthist())
		prevhist = lambda x: scroll.setstr(history.prevhist())
		#preserve docstrings for getKeynames
		nexthist.__doc__ = history.nexthist.__doc__
		prevhist.__doc__ = history.prevhist.__doc__
		self._keys.update({
			curses.KEY_UP:		nexthist
			,curses.KEY_DOWN:	prevhist
		})

class listOverlay(overlayBase):
	'''Display a list of objects, optionally drawing something at the end of each line'''
	replace = True
	#worst case column: |(value[0])...(value[1])|
	#				    1    2     345  6	    7
	#worst case rows: |(list member)|(RESERVED)
	#				  1	2			3
	setmins(7,3)
	def __init__(self,parent,outList,drawOther = None,modes = [""]):
		overlayBase.__init__(self,parent)
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
		'''Display a list in a box, basically. If too long, it gets shortened with an ellipsis in the middle'''
		lines[0] = box.top()
		size = self.parent.y-2
		maxx = self.parent.x-2
		#which portion of the lmaxyist is currently displaced
		partition = (self.it//size)*size
		#get the partition of the list we're at, pad the list
		subList = self.list[partition:partition+size]
		subList = subList + ["" for i in range(size-len(subList))]
		#display lines
		for i,value in enumerate(subList):
			half = maxx//2
			#add an elipsis in the middle of the string if it can't be displayed; also, right justify
			row = (len(value) > maxx) and value[:max(half,1)] + "..." + value[min(-half+3,-1):] or value
			row = box.just(row)
			if value and self._drawOther is not None:
				rowcol = coloring(row)
				self._drawOther(rowcol,i+partition)
				row = str(rowcol)
			if i+partition == self.it:
				row = SELECTED(row)
			else:
				row += CLEAR_FORMATTING
			lines[i+1] = box.noform(row)
		lines[-1] = box.bottom(self._modes[self.mode])
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

class colorOverlay(overlayBase):
	'''Display 3 bars for red, green, and blue. Allows exporting of color as hex'''
	replace = True
	NAMES = ["Red","Green","Blue"]
	#worst case column: |Red  GreenBlue |
	#		  			123456789ABCDEFGH = 17
	#worst case rows: |(color row) (name)(val) (hex)|(RESERVED)
	#		  1	2     3	 4	5 6  7  8
	setmins(17,8)
	def __init__(self,parent,initcolor = [127,127,127]):
		overlayBase.__init__(self,parent)
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
			,curses.KEY_UP:		staticize(self.increment,1)
			,curses.KEY_DOWN:	staticize(self.increment,-1)
			,curses.KEY_PPAGE:	staticize(self.increment,10)
			,curses.KEY_NPAGE:	staticize(self.increment,-10)
			,curses.KEY_HOME:	staticize(self.increment,255)
			,curses.KEY_END:	staticize(self.increment,-255)
			,curses.KEY_LEFT:	staticize(self.chmode,-1)
			,curses.KEY_RIGHT:	staticize(self.chmode,1)
		})
	def __call__(self,lines):
		'''Display 3 bars, their names, values, and string in hex'''
		wide = (self.parent.x-2)//3 - 1
		space = self.parent.y-7
		lines[0] = box.top()
		for i in range(space):
			string = ""
			#draw on this line (ratio of space alotted to line number = ratio of number to 255)
			for j in range(3):
				if ((space-i)*255 < (self.color[j]*space)):
					string += getColor(rawNum(j+2))
				string += " " * wide + CLEAR_FORMATTING + " "
			#justify (including escape sequence length)
			lines[i+1] = box.noform(box.just(string))
		sep = box.part("")
		lines[-6] = sep
		names,vals = "",""
		for i in range(3):
			names += centered(self.NAMES[i],wide,		i==self._rgb)
			vals += centered(str(self.color[i]),wide,	i==self._rgb)
		lines[-5] = box.part(names) #4 lines
		lines[-4] = box.part(vals) #3 line
		lines[-3] = sep #2 lines
		lines[-2] = box.part(self.getHex().rjust(int(wide*1.5)+3)) #1 line
		lines[-1] = box.bottom() #last line
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

class inputOverlay(textOverlay):
	'''Replacement? for input()'''
	replace = False
	def __init__(self,parent,prompt,password = False,end = False):
		textOverlay.__init__(self,parent)
		self._done = False
		self._prompt = prompt
		self._prompts,self._numprompts = breaklines(self._prompt,parent.x-2)
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
		lines[start] = box.top()
		for i,j in enumerate(self._prompts):
			lines[start+i+1] = box.part(j)
		#preserve the cursor position save
		lines[end+1] = box.bottom()
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
		return -1
	def remove(self):
		if not self.index and not self._done: self.parent.active = False
		super().remove()
	def resize(self,newx,newy):
		super().resize(newx,newy)
		self._prompts,self._numprompts = breaklines(self._prompt,newx-2)

	def waitForInput(self):
		'''All input is non-blocking, so we have to poll from another thread'''
		while not self._done:
			time.sleep(.1)
		return str(self.text)
	def runOnDone(self,func):
		'''Start another thread and run func after valid poll'''
		def onDone():
			result = self.waitForInput()
			if result: func(result)
		newThread = Thread(target=onDone)
		newThread.daemon = True
		newThread.start()

class commandOverlay(textOverlay):
	replace = False
	history = history()	#global command history
	def __init__(self,parent = None):
		textOverlay.__init__(self,parent)
		self.text.setnonscroll(CHAR_COMMAND)
		self.controlhistory(self.history,self.text)
		self._keys.update({
			10:		staticize(self._run)
			,127:	staticize(self._backspacewrap)
		})
		self._altkeys.update({
			127:	lambda: -1
		})
	def __call__(self,lines):
		lines[-1] = 'COMMAND'
	def _backspacewrap(self):
		'''Backspace a char, or quit out if there are no chars left'''
		if not str(self.text): return -1
		self.text.backspace()
	def _run(self):
		'''Run command'''
		text = str(self.text)
		if text == CHAR_COMMAND: self.history.append(text)
		space = text.find(' ')
		commandname = space == -1 and text or text[:space]
		if commandname not in _commands:
			self.parent.newBlurb("Command \"{}\" not found".format(commandname))
			return -1
		command = _commands[commandname]
		try:
			add = command(self.parent,text[space+1:].split(' '))
			if isinstance(add,overlayBase):
				self.swap(add)
				return
		except Exception as exc:
			dbmsg('%s occurred in command %s: %s' % \
				(type(exc).__name__,commandname, exc))
		except KeyboardInterrupt: pass
		return -1

class escapeOverlay(overlayBase):
	'''Overlay for redirecting input after \ is pressed'''
	replace = False
	def __init__(self,parent,scroll):
		overlayBase.__init__(self,parent)
		self._keys.update({
			-1:		quitlambda
			,10:		quitlambda
			,ord('n'):	lambda x: scroll.append('\n') or -1
			,ord('\\'):	lambda x: scroll.append('\\') or -1
			,ord('t'):	lambda x: scroll.append('\t') or -1
		})

class confirmOverlay(overlayBase):
	'''Overlay to confirm selection confirm y/n (no slash)'''
	replace = False
	def __init__(self,parent,prompt,confirmfunc):
		overlayBase.__init__(self,parent)
		self.parent.holdBlurb(prompt)
		self._keys.update({ #run these in order
			ord('y'):	lambda x: confirmfunc() or self.parent.releaseBlurb() or -1
			,ord('n'):	lambda x: self.parent.releaseBlurb() or -1
		})

class mainOverlay(textOverlay):
	'''The main overlay. Optionally pushes time messages every 10 minutes '''+\
	'''and can refresh blurbs every few seconds'''
	replace = True
	#sequence between messages to draw reversed
	INDENT = "    "
	_msgSplit = "\x1b" 
	def __init__(self,parent,pushtimes = True):
		textOverlay.__init__(self,parent)
		self._pushtimes = pushtimes
		self.history = history()
		self.clear()
		self.controlhistory(self.history,self.text)
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
		lines[-1] = box.CHAR_HSPACE*self.parent.x
	#method overloading---------------------------------------------------------
	def _input(self,chars):
		'''Input some text'''
		if not str(self.text) and len(chars) == 1 and \
		chars[0] == ord(CHAR_COMMAND):
			commandOverlay(self.parent).add()
			return
		#allow unicode input
		return textOverlay._input(self,chars)
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
		'''Quit timeloop (if it hasn't already exited)'''
		super().remove()
		self._pushtimes = False
		if not self.index:
			self.parent.active = False
	def resize(self,newx,newy):
		'''Resize scrollable and maybe draw lines again'''
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
		'''Add a newline if the next character is n, or a tab if the next character is t'''
		escapeOverlay(self.parent,self.text).add()
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
	def selectup(self):
		'''Select message up'''
		#go up the number of lines of the "next" selected message
		upmsg = self._getnextmessage(1)
		#but only if there is a next message
		if not upmsg: soundBell()
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
		'''Frontend for getting the selected message. Returns a list of ''' + \
		'''length three: the message, an argument tuple, and how many lines'''
		return self._allMessages[-self._selector]
	def redolines(self,width = None,height = None):
		'''Redo lines, if current lines does not represent the unfiltered messages ''' + \
		'''or if the width has changed'''
		if width is None: width = self.parent.x
		if height is None: height = self.parent.y
		newlines = []
		numup,nummsg = 0,1
		while numup < (height) and nummsg <= len(self._allMessages):
			i = self._allMessages[-nummsg]
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
	def clear(self):
		'''Clear all lines, messages'''
		#these two REALLY should be private
		self._allMessages = []
		self._lines = []
		#these too because they select the previous two
		self._selector = 0
		self._unfiltup = 0
		self._linesup = 0
	def msgSystem(self, base):
		'''System message'''
		base = coloring(base)
		base.insertColor(0,rawNum(1))
		self._append(base)
		self.parent.display()
	def msgTime(self, numtime = None, predicate=""):
		'''Push a system message of the time'''
		dtime = time.strftime("%H:%M:%S",time.localtime(numtime or time.time()))
		self.msgSystem(predicate+dtime)
	def msgPost(self,post,*args):
		'''Parse a message and apply all colorizers'''
		post = coloring(post)
		for i in _colorizers:
			i(post,*args)
		self._append(post,list(args))
		self.parent.display()
	#MESSAGE PUSHING BACKEND-----------------------------------
	def _append(self,newline,args = None):
		'''Add new message. Use msgPost instead'''
		#undisplayed messages have length zero
		msg = [newline,args,0]
		self._selector += (self._selector>0)
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
		if self._selector:
			self._linesup += b+1
			self._unfiltup += 1

class nscrollable(scrollable):
	'''A scrollable that expects a main object as parent so that it '''+\
	'''can updateinput()'''
	def __init__(self,width,parent,index):
		scrollable.__init__(self,width)
		self.parent = parent
		self.index = index
	def _onchanged(self):
		self.parent.updateinput()

#MAIN CLIENT--------------------------------------------------------------------
class _schedule:
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
		'''Change the value of debounce. If bounce is on a falling edge, run queued functions'''
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

class main:
	'''Main class; handles all IO and defers to overlays'''
	last = 0
	def __init__(self):
		self._screen = curses.initscr()		#init screen
		#sadly, I can't put this in main.loop to make it more readable
		curses.noecho(); curses.cbreak(); self._screen.keypad(1) #setup curses
		self._screen.nodelay(1)	#don't wait for enter to get input

		self._schedule = _schedule()
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
		lines = ["" for i in range(self.y)]
		#justify number of lines
		#start with the last "replacing" overlay, then draw all overlays afterward
		for start in range(self._lastReplace,len(self._ins)):
			self._ins[start](lines)
		#main display method: move to top of screen
		_moveCursor()
		curses.curs_set(0)
		#draw each line in lines
		for i in lines:
			#delete the rest of the garbage on the line, newline
			print(i,end='\x1b[K\n\r') 
		curses.curs_set(1)
		print(CHAR_RETURN_CURSOR,end='')
	def _updateinput(self):
		'''Input display backend'''
		if not (self.active and self.candisplay): return
		if not self._scrolls: return	#no textoverlays added, but how are you firing this
		string = format(self._scrolls[-1])
		_moveCursor(self.y+1)
		print('{}\x1b[K'.format(string),end=CHAR_RETURN_CURSOR)
	def _printblurb(self,string,time):
		'''Blurb display backend'''
		if not (self.active and self.candisplay): return
		if self.last < 0: return
		if self._blurbQueue:
			if string:
				vector,_ = breaklines(string,self.x)
				self._blurbQueue.extend(vector)
			string = self._blurbQueue.pop(0)
		if string == "":	#advance queue
			if self._blurbQueue:
				string = self._blurbQueue.pop(0)
			else:
				string = ""
		self.last = time
		_moveCursor(self.y+2)
		if strlen(string) > self.x:
			vector,_ = breaklines(string,self.x)
			string = vector[0]
			self._blurbQueue.extend(vector[1:])
		print('{}\x1b[K'.format(string),end=CHAR_RETURN_CURSOR)
	def _releaseblurb(self):
		'''Release blurb backend'''
		self.last = time.time()
	def _updateinfo(self,right,left):
		'''Info window backend'''
		if not (self.active and self.candisplay): return
		_moveCursor(self.y+3)
		self._bottom_edges[0] = left or self._bottom_edges[0]
		self._bottom_edges[1] = right or self._bottom_edges[1]
		room = self.x - len(self._bottom_edges[0]) - len(self._bottom_edges[1])
		if room < 1: return
		#selected, then turn off
		print('\x1b[7m{}{}{}\x1b[0m'.format(self._bottom_edges[0],
			" "*room,self._bottom_edges[1]),end=CHAR_RETURN_CURSOR)
	#Display Frontends----------------------------------------------------------
	def display(self):
		self._schedule(self._display)
	def updateinput(self):
		'''Update input'''
		self._schedule(self._updateinput)
	def newBlurb(self,message = ""):
		'''Add blurb. Use in conjunction with mainOverlay to erase'''
		self._schedule(self._printblurb	,message,time.time())
	def holdBlurb(self,string):
		'''Hold blurb. Sets self.last to -1, making newBlurb not draw'''
		self._schedule(self._printblurb	,string	,-1)
	def releaseBlurb(self):
		'''Release blurb. Sets self.last to a valid time, making newBlurb start drawing again'''
		self._schedule(self._releaseblurb)
		self._schedule(self._printblurb,'',time.time())
	def updateinfo(self,right = None,left = None):
		'''Update screen bottom'''
		self._schedule(self._updateinfo,right,left)
	#Overlay Frontends---------------------------------------------------------
	def addOverlay(self,new):
		'''Add overlay'''
		if not isinstance(new,overlayBase): return
		new.index = len(self._ins)
		self._ins.append(new)
		if new.replace: self._lastReplace = new.index
		#display is not strictly called beforehand, so better safe than sorry
		self.display()
	def popOverlay(self,overlay):
		"""Pop the overlay 'overlay'"""
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
	def addScrollable(self):
		newScroll = nscrollable(self.x,self,len(self._scrolls))
		self._scrolls.append(newScroll)
		self.updateinput()
		return newScroll
	def popScrollable(self,which):
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
				i.remove()
	#Frontends------------------------------------------------------------------
	def resize(self):
		'''Resize the GUI'''
		newy, newx = self._screen.getmaxyx()
		newy -= RESERVE_LINES
		box.width = newx
		try:	#TODO formattingexception's name seems vauge here
			if newy < _MIN_Y or newx < _MIN_X:
				raise FormattingException()
			for i in self._ins:
				i.resize(newx,newy)
		except FormattingException:
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
	main_instance = main()
	main_instance.resize()
	#daemonize functions bot_thread
	bot_thread = Thread(target=main_instance.catcherr(target,main_instance,*args))
	bot_thread.daemon = True
	bot_thread.start()
	main_instance.loop()	#main program loop
	if lasterr:
		raise lasterr

#display list of defined commands
@command('help')
def listcommands(parent,args):
	def select(self):
		new = commandOverlay(parent)
		new.text.append(self.list[self.it])
		self.swap(new)

	commandsList = listOverlay(parent,list(_commands))
	commandsList.addKeys({
		'enter':select
	})
	return commandsList

@command('q')
def quit(parent,args):
	parent.active = False
