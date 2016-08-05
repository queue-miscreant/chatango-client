#!/usr/bin/env python3
#client.display.py
'''Client module with single-byte curses input uses a
system of overlays, pulling input from the topmost
one. Output is done not with curses display, but various
different print() calls.'''

try:
	import curses
except ImportError:
	raise ImportError("ERROR WHILE IMPORTING CURSES"+
			", is this running on Windows cmd?")
import sys
from os import environ
if not sys.stdout.isatty(): #check if terminal
	raise IOError("This script is not intended to be piped")
#escape has delay typically
environ.setdefault('ESCDELAY', '25')

#stupid? yes.
from .coloring import *
from .fitting import *
import time
from threading import Thread

active = False
lastlinks = []
lasterr = None

#guessed terminal dimensions
DIM_X = 40
DIM_Y = 70
RESERVE_LINES = 3
#break if smaller than these
_MIN_X = 0
_MIN_Y = RESERVE_LINES
def setmins(newx,newy):
	'''Set minimum width/height'''
	global _MIN_X,_MIN_Y
	_MIN_X=max(_MIN_X,newx)
	_MIN_Y=max(_MIN_Y,newy)

#DEBUG STUFF--------------------------------------------------------------------
def dbmsg(*args):
	with open("debug","a+") as a:
		for i in args:
			a.write(str(i)+"\t")
		a.write("\n")
		a.close()

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

class KeyException(Exception):
	'''Exception for keys-related errors in client.display'''
	pass

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
colorers = []
commands = {}
filters = []

#decorators for containers
def colorer(func):
	'''Add function as a colorer.'''
	colorers.append(func)
def filter(func):
	'''Add function as a filter.'''
	filters.append(func)
def command(commandname):
	'''Add function as a command `commandname`'''
	def wrapper(func):
		commands[commandname] = func
	return wrapper

#OVERLAY HELPERS------------------------------------------------------------------
CHAR_RETURN_CURSOR = '\x1b[u\n\x1b[A'
CHAR_COMMAND = "/"
		
def centered(string,width,isselected):
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
	#lambdas
	noform = lambda x: box.CHAR_VSPACE + x + box.CHAR_VSPACE
	def format(left,string,right,justchar = ' '):
		'''Format and justify part of box'''
		return '%s%s%s' % (left,box.just(string,justchar),right)
	def just(string,justchar = ' '):
		'''Justify string by column width'''
		return '%s%s' % (string,justchar*(DIM_X-2-strlen(string)))
	def part(fmt = '') :
		'''Format with vertical spaces'''
		return box.format(box.CHAR_VSPACE,fmt,box.CHAR_VSPACE)
	def top(fmt = ''):
		'''Format with box tops'''
		return box.format(box.CHAR_TOPL,fmt,box.CHAR_TOPR,box.CHAR_HSPACE)
	def bottom(fmt = ''):
		'''Format with box bottoms'''
		return box.format(box.CHAR_BTML,fmt,box.CHAR_BTMR,box.CHAR_HSPACE)

def scrollablecontrol(scroll):
	'''Return a dictionary with standard controls for scrollable `scroll`'''
	return {
		127:			staticize(scroll.backspace)
		,curses.KEY_DC:		staticize(scroll.delchar)
		,curses.KEY_SHOME:	staticize(scroll.clear)
		,curses.KEY_RIGHT:	staticize2(scroll.movepos,1)
		,curses.KEY_LEFT:	staticize2(scroll.movepos,-1)
		,curses.KEY_HOME:	staticize(scroll.home)
		,curses.KEY_END:	staticize(scroll.end)
	}

def historycontrol(history,scroll):
	'''Return a dictionary with standard controls for history `history`'''
	return {
		curses.KEY_UP:		lambda x:	scroll.setstr(history.nexthist())
		,curses.KEY_DOWN:	lambda x:	scroll.setstr(history.prevhist())
	}

class history:
	'''Container class for historical entries, a la an actual shell'''
	def __init__(self):
		self.history = []
		self._selhis = 0
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
	def appendhist(self,new):
		'''Add new entry in history'''
		self.history.append(new)
		self.history = self.history[-50:]
		self._selhis = 0

#DISPLAY/OVERLAY CLASSES----------------------------------------------------------
class DisplayException(Exception):
	'''Exception for display-related errors in client.display'''
	pass

def _moveCursor(x=0):
	print("\x1b[%d;f"%x,end=CLEAR_FORMATTING)
def soundBell():
	print('\a',end="")

#please don't need these
quitlambda = lambda x: -1
staticize = lambda x: lambda y: x()
staticize2 = lambda x,y: lambda z: x(y)

def onkey(keyname):
	'''Wrapper for adding keys to client.display.mainOverlay'''
	def wrapper(func):
		try:
			mainOverlay.addoninit[_VALID_KEYNAMES[keyname]] = func
		except:	raise KeyException("key %s not defined" % keyname)
	return wrapper

class overlayBase:
	'''An overlay is a class that redirects input and modifies a list of strings'''
	def __init__(self):
		self._altkeys =	 {None:	lambda: -1}
		self._keys =	 {27:	self._callalt}
	def __call__(self,chars):
		'''Redirect input with this overlay'''
		try:
			char = _KEY_LUT[chars[0]]
		except: char = chars[0]
		if char in self._keys:	#ignore the command character and trailing -1
			return self._keys[char](chars[1:-1] or [None]) or self._post()
		elif char in range(32,255) and -1 in self._keys:	#ignore the trailing -1
			return self._keys[-1](chars[:-1]) or self._post()
	def _callalt(self,chars):
		'''Call a key from _altkeys.'''
		return chars[0] in self._altkeys and self._altkeys[chars[0]]()
	def _post(self):
		'''Overridable function. Run after keypress if false (, None...) is returned'''
		pass
	def display(self,lines):
		'''Overridable function. Modify lines by address (i.e lines[value]) to display from _main'''
		pass
	def addKeys(self,newFunctions = {}):
		'''Nice method to add keys whenever'''
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
		'''Add resize. Done automatically on addOverlay'''
		self._keys[curses.KEY_RESIZE] = staticize(other.resize)

class listOverlay(overlayBase):
	'''Display a list of objects, optionally drawing something at the end of each line'''
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
			,ord('l'):	staticize2(self.chmode,1)
			,ord('h'):	staticize2(self.chmode,-1)
			,ord('`'):	quitlambda
			,curses.KEY_DOWN:	staticize2(self.increment,1)
			,curses.KEY_UP:		staticize2(self.increment,-1)
			,curses.KEY_RIGHT:	staticize2(self.chmode,1)
			,curses.KEY_LEFT:	staticize2(self.chmode,-1)
		})
	
	#predefined list iteration methods
	def increment(self,amt):
		'''Move self.it by amt'''
		if not self._numentries: return
		self.it += amt
		self.it %= self._numentries
	def chmode(self,amt):
		'''Move to mode amt over, with looparound'''
		self.mode = (self.mode + amt) % self._nummodes
	
	def display(self,lines):
		'''Display a list in a box, basically. If too long, it gets shortened with an ellipsis in the middle'''
		lines[0] = box.top()
		size = DIM_Y-RESERVE_LINES-2
		maxx = DIM_X-2
		#which portion of the lmaxyist is currently displaced
		partition = (self.it//size)*size
		#get the partition of the list we're at, pad the list
		subList = self.list[partition:partition+size]
		subList = subList + ["" for i in range(size-len(subList))]
		#display lines
		for i,value in enumerate(subList):
			half = maxx//2
			#add an elipsis in the middle of the string if it can't be displayed; also, right justify
			row = (len(value) > maxx) and value[:max(half-3,1)] + "..." + value[-half:] or value
			row += CLEAR_FORMATTING
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

class colorOverlay(overlayBase):
	'''Display 3 bars for red, green, and blue. Allows exporting of color as hex'''
	replace = True
	NAMES = ["Red","Green","Blue"]
	#worst case column: |Red  GreenBlue |
	#		    123456789ABCDEFGH = 17
	#worst case rows: |(color row) (name)(val) (hex)|(RESERVED)
	#		  1	2     3	 4	5 6  7  8
	setmins(17,8+RESERVE_LINES)
	def __init__(self,initcolor = [127,127,127]):
		overlayBase.__init__(self)
		#allow setting from hex value
		if isinstance(initcolor,str):
			self.setHex(initcolor)
		else:
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
		
	def display(self,lines):
		'''Display 3 bars, their names, values, and string in hex'''
		wide = (DIM_X-2)//3 - 1
		space = DIM_Y-RESERVE_LINES-7
		lines[0] = box.top()
		for i in range(space):
			string = ""
			#draw on this line (ratio of space alotted to line number = ratio of number to 255)
			for j in range(3):
				if ((space-i)*255 < (self.color[j]*space)):
					string += getColor(j+2,False)
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
		return lines

class inputOverlay(overlayBase):
	'''Replacement? for input()'''
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
	def _finish(self):
		'''Regular stop (i.e, with enter)'''
		self._done = True
		return -1
	def _stop(self):
		'''Premature stops, clear beforehand'''
		if self._end:
			#raising SystemExit is dodgy, since curses.endwin won't get called
			global active
			active = False
		self.text.clear()
		return -1
	def display(self,lines):
		'''Display the text in roughly the middle, in a box'''
		start = DIM_Y//2 - 2
		room = DIM_X-2
		lines[start] = box.top()
		#make sure we're not too long
		inp = self.text.display()
		#preserve the cursor position save
		if self._password:
			inp = CHAR_CURSOR.join('*'*len(i) for i in inp.split(CHAR_CURSOR))
		lines[start+1] = box.part(self._prompt + inp)
		lines[start+2] = box.bottom()
	def waitForInput(self):
		'''All input is non-blocking, so we have to poll from another thread'''
		while not self._done:
			time.sleep(.1)
		return str(self.text)

class commandOverlay(inputOverlay):
	replace = False
	history = history()
	def __init__(self,client):
		inputOverlay.__init__(self,'')
		self.parent = client
		self._keys.update(historycontrol(self.history,self.text))
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
		if text: self.history.appendhist(text)
		space = text.find(' ')
		command = space == -1 and text or text[:space]
		try:
			command = commands[command]
			add = command(self.parent,text[space+1:].split(' '))
			if isinstance(add,overlayBase):
				self.parent.replaceOverlay(add)
				return
		except Exception as exc: dbmsg(exc)
		return -1
	def display(self,lines):
		lines[-1] = CHAR_COMMAND + self.text.display()
		return lines

class escapeOverlay(overlayBase):
	'''Overlay for redirecting input after \ is pressed'''
	replace = False
	def __init__(self,appendobj):
		overlayBase.__init__(self)
		self._keys.update({
			-1:		lambda x: -1
			,ord('n'):	lambda x: appendobj.append('\n') or -1
			,ord('\\'):	lambda x: appendobj.append('\\') or -1
			,ord('t'):	lambda x: appendobj.append('\t') or -1
		})

class confirmOverlay(overlayBase):
	'''Overlay to confirm selection confirm y/n (no slash)'''
	replace = False
	def __init__(self,confirmfunc):
		overlayBase.__init__(self)
		self._keys.update({
			ord('y'):	lambda x: confirmfunc() or -1
			,ord('n'):	quitlambda
		})

class mainOverlay(overlayBase):
	'''The main overlay'''
	replace = True
	addoninit = {}
	#sequence between messages to draw reversed
	_msgSplit = "\x1b" 
	def __init__(self,parent):
		overlayBase.__init__(self)
		self.text = scrollable(DIM_X)
		self.history = history()
		self.parent = parent
		self.clearlines()
		self._keys.update(scrollablecontrol(self.text))
		self._keys.update(historycontrol(self.history,self.text))
		self._keys.update({
			-1:			self._input
			,ord('\\'):		staticize(self._replaceback)
		})
		self._altkeys.update({
			ord('k'):		self.selectup		#muh vim t. me
			,ord('j'):		self.selectdown
			,127:			self.text.delword
		})
		self.addKeys(self.addoninit)
	#stop selecting
	def _post(self):
		if self._selector:
			self._selector = 0
			self._linesup = 0
			self._unfiltup = 0
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
		#go up the number of lines of the "next" selected message
		upmsg = self._getnextmessage(1)
		#but only if there is a next message
		if not upmsg: soundBell()
		else: self._linesup += upmsg+1
		return 1 #don't stop selecting
	def selectdown(self):
		#go down the number of lines of the currently selected message
		self._linesup = max(0,self._linesup-self.getselect()[2]-1)
		self._getnextmessage(-1)
		if not self._selector:
			self.parent.display()
		return 1
	def _getnextmessage(self,step):
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
		
	#-------------------------FRONTENDS-------------------------
	def addOverlay(self,new):
		self.parent.addOverlay(new)
	#get selector
	def isselecting(self):
		return self._selector
	#frontend for self._allMessages[self._selector] that returns the right one
	def getselect(self):
		return self._allMessages[-self._selector]
	#does what it says
	def redolines(self):
		newlines = []
		#get the last terminal line number of messages (worst case)
		for i in self._allMessages[-(DIM_Y-RESERVE_LINES):]:
			try:
				if any(j(*i[1]) for j in filters):
					i[2] = 0
					continue
			except: pass
			a,b = breaklines(i[0],DIM_X)
			newlines += a
			i[2] = b
			newlines.append(self._msgSplit)
		self._lines = newlines
	#second verse, same as the first
	def clearlines(self):
		#these two REALLY should be private
		self._allMessages = []
		self._lines = []
		#these too because they select the previous two
		self._selector = 0
		self._unfiltup = 0
		self._linesup = 0

	#-------------------------BACKENDS-------------------------
	#add new messages
	def append(self,newline,args = None):
		#undisplayed messages have length zero
		msg = [newline,args,0]
		self._selector += (self._selector>0)
		try:
			if any(i(*args) for i in filters):
				self._allMessages.append(msg)
				return
		except: pass
		a,b = breaklines(newline,DIM_X)
		self._lines += a
		msg[2] = b
		self._allMessages.append(msg)
		self._lines.append(self._msgSplit)
		if self._selector:
			self._linesup += b+1
			self._unfiltup += 1

	#add lines into lines supplied
	def display(self,lines):
		#seperate traversals
		selftraverse,linetraverse = -1,-2
		lenself, lenlines = len(self._lines),len(lines)
		msgno = 0
		#go backwards by default
		direction = -1
		if self._linesup-self._selector >= lenlines:
			direction = 1
			msgno = self._selector
			selftraverse,linetraverse = -self._linesup,-lenlines
			lenself, lenlines = -1,-2
			
		while (selftraverse*direction) <= lenself and \
			(linetraverse*direction) <= lenlines:

			if self._lines[selftraverse] == self._msgSplit:
				selftraverse += direction #disregard this line
				msgno -= direction #count lines down downward, up upward
				continue
			reverse = (msgno == self._unfiltup) and SELECT_AND_MOVE or ""
			lines[linetraverse] = reverse + self._lines[selftraverse]
			selftraverse += direction
			linetraverse += direction
		lines[-1] = box.CHAR_HSPACE*DIM_X

#MAIN CLIENT--------------------------------------------------------------------
class BotException(Exception):
	'''Exception for incorrect bots passed into client.display'''
	pass

class botclass:
	parent = None
	def setparent(self,overlay):
		if not isinstance(overlay,_main):
			raise BotException("botclass.setparent attempted on object other than display._main")
		self.parent = overlay

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

class _main:
	'''Main class; handles all IO and defers to overlays'''
	_screen = None
	_last = 0
	def __init__(self,chatbot):
		if not isinstance(chatbot,botclass):
			raise BotException("%s not descendent of client.botclass"%\
			type(chatbot).__name__)
		self._schedule = _schedule()
		self._bottom_edges = [" "," "]

		self.candisplay = 1
		chatbot.setparent(self)
		self.over = mainOverlay(self)
		self.over.addResize(self)
		#input/display stack
		self._ins = [self.over]
	#=------------------------------=
	#|	Loop Backends		|
	#=------------------------------=
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
			global active
			active = False
			return
		return self._ins[-1](chars)
	def _loop(self):
		'''Main client loop'''
		while active:
			if self._input() == -1:
				self._ins.pop()
				if not self._ins: break #insurance
				self.resize()
				
			if len(self._ins)-1 or self.over.isselecting():
				self.display()
			else:
				self.updateinput()
	def _timeloop(self):
		'''Prints the current time every 10 minutes. Also handles erasing blurbs'''
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
	#=------------------------------=
	#|	Display Backends	|
	#=------------------------------=
	def _display(self):
		'''Display backend'''
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
		_moveCursor()
		curses.curs_set(0)
		#draw each line in lines
		for i in lines:
			#delete the rest of the garbage on the line, newline
			print(i,end="\x1b[K\n\r") 
		curses.curs_set(1)
		print(CHAR_RETURN_CURSOR,end='')
	def _printblurb(self,string):
		'''Blurb display backend'''
		self._last = time.time()
		if not self.candisplay: return
		_moveCursor(DIM_Y-RESERVE_LINES+2)
		if strlen(string) > DIM_X:
			string = string[fitwordtolength(string,DIM_X-3):]+'...'
		print(string+'\x1b[K',end=CHAR_RETURN_CURSOR)
	def _updateinput(self):
		'''Input display backend'''
		if not self.candisplay: return
		string = self.over.text.display()
		_moveCursor(DIM_Y-RESERVE_LINES+1)
		print(string+'\x1b[K',end=CHAR_RETURN_CURSOR)
	def _updateinfo(self,right,left):
		'''Info window backend'''
		if not self.candisplay: return
		_moveCursor(DIM_Y)
		self._bottom_edges[0] = left or self._bottom_edges[0]
		self._bottom_edges[1] = right or self._bottom_edges[1]
		room = DIM_X - len(self._bottom_edges[0]) - len(self._bottom_edges[1])
		if room < 1:
			return
		#selected, then turn off
		print("\x1b[7m{}{}{}\x1b[0m".format(self._bottom_edges[0],
			" "*room,self._bottom_edges[1]),end=CHAR_RETURN_CURSOR)

	#=------------------------------=
	#|	Display Frontends	|
	#=------------------------------=
	def display(self):
		self._schedule(self._display)
	def msgSystem(self, base):
		'''System message'''
		self.over.append(getColor(1,False)+base+CLEAR_FORMATTING)
		self.display()
	def msgTime(self, numtime = None, predicate=""):
		'''Push a system message of the time'''
		dtime = time.strftime("%H:%M:%S",time.localtime(numtime or time.time()))
		self.msgSystem(predicate+dtime)
	def msgPost(self,post,*args):
		'''Parse a message and apply all colorers'''
		post = coloring(post)
		#run each colorer on the coloring object
		for i in colorers:
			i(post,*args)
		#push the message and move the cursor back to the input window
		self.over.append(str(post),list(args))
		self.display()
	def updateinput(self):
		'''Update input'''
		self._schedule(self._updateinput)
	def newBlurb(self,message = ""):
		'''(Roughly) 5 second blurb'''
		self._schedule(self._printblurb,message)
	def updateinfo(self,right = None,left = None):
		'''Update screen bottom'''
		self._schedule(self._updateinfo,right,left)

	#=------------------------------=
	#|	Overlay Frontends	|
	#=------------------------------=
	def addOverlay(self,new):
		'''Add overlay'''
		if not isinstance(new,overlayBase): return
		new.addResize(self)
		self._ins.append(new)
		#yes, this is still too fast
		time.sleep(.01)
		self.display()
		self.updateinfo() #this looks ugly otherwise
	def replaceOverlay(self,new):
		'''Replace the top overlay'''
		if len(self._ins) == 1: return
		self._ins.pop()
		self.addOverlay(new)
	def resize(self):
		'''Resize the GUI'''
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

	#--------------------------------
	def catcherr(self,func,*args):
		'''Catch error and end client'''
		def wrap():
			try:
				func(*args)
			except Exception as e:
				global lasterr,active
				lasterr = e
				active = False
				curses.ungetch('\x1b')
		return wrap

	def start(self,screen,main_function):
		'''Start _loop, _timeloop, and bot_thread (threaded main)'''
		global active
		active = True
		self._screen = screen
		self._screen.nodelay(1)
		self.resize()
		#daemonize functions
		#printtime
		printtime = Thread(target=self._timeloop)
		printtime.daemon = True
		printtime.start()
		#bot_thread
		bot_thread = Thread(target=self.catcherr(main_function))
		bot_thread.daemon = True
		bot_thread.start()
		self._loop()
		active = False

def start(bot_object,main_function):
	'''Start the client. Run this!'''
	client = _main(bot_object)
	#start 
	scr = curses.initscr()
	curses.noecho(); curses.cbreak(); scr.keypad(1)
	try:
		client.start(scr, main_function)
	finally:
		curses.echo(); curses.nocbreak(); scr.keypad(0)
		curses.endwin()
	if lasterr:
		raise lasterr

#display list of defined commands
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
	
#clear formatting (reverse, etc) after each message
@colorer
def removeFormatting(msg,*args):
	msg + CLEAR_FORMATTING
