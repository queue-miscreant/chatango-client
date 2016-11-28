#!/usr/bin/env python3
#client.display.py
'''
Module for formatting; support for fitting strings to column
widths and ANSI color escape string manipulations. Also contains
generic string containers.
'''
#TODO fix format() in Scrollable
#		to fix, display must be from the right side,rather than the left
#		we still have to accumulate string length...
#		maybe just measure display as both distance and columns  <- this
import re
from .wcwidth import wcwidth

#all imports needed by overlay.py
__all__ =	["CLEAR_FORMATTING","CHAR_CURSOR","CHAR_RETURN_CURSOR","SELECT"
			,"SELECT_AND_MOVE","dbmsg","rawNum","strlen","getColor"
			,"Coloring","Scrollable","Tokenize"]

#REGEXES------------------------------------------------------------------------
_SANE_TEXTBOX =		r"\s\-/`~,;"			#sane textbox splitting characters
_LAST_COLOR_RE =	re.compile('\x1b'+r"\[[^m]*3[^m]*m")	#find last color inserted (contains a 3)
_UP_TO_WORD_RE =	re.compile("([^{0}]*[{0}])*[^{0}]+[{0}]*".format(_SANE_TEXTBOX))	#sane textbox word-backspace
_LINE_BREAKING = "- 　"	#line breaking characters
#valid color names to add
_COLOR_NAMES =	["black"
				,"red"
				,"green"
				,"yellow"
				,"blue"
				,"magenta"
				,"cyan"
				,"white"
				,""
				,"none"]
#names of effects, and a tuple containing 'on' and 'off'
_EFFECTS =	[("\x1b[7m","\x1b[27m")
			,("\x1b[4m","\x1b[24m")
			]
_NUM_EFFECTS = len(_EFFECTS)
_EFFECTS_BITS = (1 << _NUM_EFFECTS)-1
_CAN_DEFINE_EFFECTS = True
#storage for defined pairs
_COLORS =	["\x1b[39;22;49m"	#Normal/Normal
			,"\x1b[31;22;47m"	#Red/White
			,"\x1b[31;22;41m"	#red
			,"\x1b[32;22;42m"	#green
			,"\x1b[34;22;44m"	#blue
			]
_NUM_PREDEFINED = len(_COLORS)
CHAR_CURSOR = "\x1b[s"
CHAR_RETURN_CURSOR = "\x1b[u\n\x1b[A"
SELECT = _EFFECTS[0][0]
SELECT_AND_MOVE = CHAR_CURSOR + SELECT
CLEAR_FORMATTING = "\x1b[m"
_TABLEN = 4
#arbitrary number of characters a scrollable can have and not scroll
MAX_NONSCROLL_WIDTH = 5

#DEBUG STUFF--------------------------------------------------------------------
def dbmsg(*args):
	'''
	Since the client runs in a contained curses session, printing more
	is out of the question. So just print to file `debug`
	'''
	with open("debug","a+") as a:
		for i in args:
			a.write(str(i)+'\t')
		a.write('\n')

#COLORING STUFF-----------------------------------------------------------------
class DisplayException(Exception):
	'''Exception for client.display'''
	pass

def defColor(fore, back = "none"):
	'''Define a new foreground/background pair, with optional intense color'''
	global _COLORS
	pair = "\x1b[3"
	if isinstance(fore,int):
		pair += "8;5;%d" % fore;
	else:
		pair += str(_COLOR_NAMES.index(fore));
	if isinstance(back,int):
		pair += ";48;5;%d" % back;
	else:
		pair += ";4%d" % _COLOR_NAMES.index(back)
	_COLORS.append(pair+"m")
def defEffect(on,off):
	'''Define a new effect, turned on with `on`, and off with `off`'''
	if not _CAN_DEFINE_EFFECTS:
		raise DisplayException("cannot define effect; a Coloring object already exists")
	global _EFFECTS,_NUM_EFFECTS,_EFFECTS_BITS
	_EFFECTS.append((on,off))
	_NUM_EFFECTS += 1
	_EFFECTS_BITS = (_EFFECTS_BITS << 1) | 1

def def256colors():
	for i in range(256):
		defColor(i)

def getColor(c):
	'''insertColor without position or coloring object'''
	try:
		return _COLORS[c + _NUM_PREDEFINED]
	except IndexError:
		raise DisplayException("Color definition %d not found"%c)

def rawNum(c):
	'''
	Get raw pair number, without respect to number of predefined ones.
	Use in conjunction with getColor or Coloring.insertColor to use
	predefined colors
	'''
	if c < 0: raise DisplayException("raw numbers must not be below 0")
	return c - _NUM_PREDEFINED

class Coloring:
	'''Container for a string and coloring to be done'''
	def __init__(self,string):
		global _CAN_DEFINE_EFFECTS
		_CAN_DEFINE_EFFECTS = False
		self._str = string
		self._positions = []
		self._formatting = []
		self._maxpos = -1
	def clear(self):
		'''Clear all positions and formatting'''
		self._maxpos = -1
		self._positions.clear()
		self._formatting.clear()
	def __repr__(self):
		'''Get the string contained'''
		return "Coloring({}, positions = {}, formatting = {})".format(repr(self._str),self._positions,self._formatting)
	def __str__(self):
		return self._str
	def __format__(self,*args):
		'''Colorize the string'''
		ret = ""
		tracker = 0
		lastEffect = 0
		for pos,form in zip(self._positions,self._formatting):
			color = form >> _NUM_EFFECTS
			nextEffect = form & _EFFECTS_BITS
			formatting = color > 0 and _COLORS[color-1] or ""
			for i in range(_NUM_EFFECTS):
				if ((1 << i) & nextEffect):
					if ((1 << i) & lastEffect):
						formatting += _EFFECTS[i][1]
					else:
						formatting += _EFFECTS[i][0]
			ret += self._str[tracker:pos] + formatting
			tracker = pos
			lastEffect = nextEffect
		ret += self._str[tracker:]
		return ret + CLEAR_FORMATTING
	def __getitem__(self,sliced):
		'''Set the string to a slice of itself'''
		self._str = self._str[sliced]
		return self
	def __add__(self,other):
		'''Set string to concatenation'''
		self._str = self._str + other
		return self
	def __radd__(self,other):
		'''__add__ but from the other side'''
		self._str = other + self._str
		for pos,i in enumerate(self._positions):
			self._positions[pos] = i + len(other)
		self._maxpos += len(other)
		return self

	def coloredAt(self,position):
		'''return a bool that represents if that position is colored yet'''
		return position in self._positions

	def _insertColor(self,position,formatting):
		'''insertColor backend that doesn't do sanity checking on formatting'''
		if position > self._maxpos:
			self._positions.append(position)
			self._formatting.append(formatting)
			self._maxpos = position
			return
		i = 0
		while position > self._positions[i]:
			i += 1
		if self._positions[i] == position:		#position already used
			effect = self._formatting[i] & _EFFECTS_BITS
			self._formatting[i] = formatting | effect
		else:
			self._positions.insert(i,position)
			self._formatting.insert(i,formatting)

	def insertColor(self,position,formatting):
		'''
		Insert positions/formatting into color dictionary
		formatting must be a proper color (in _COLORS, added with defColor)
		'''
		if position < 0: position = max(position+len(self._str),0)
		formatting += _NUM_PREDEFINED + 1
		formatting <<= _NUM_EFFECTS
		self._insertColor(position,formatting)

	def effectRange(self,start,end,formatting):
		'''
		Insert an effect at _str[start:end]
		formatting must be a number corresponding to an effect
		'''
		if start >= end: return
		effect = 1 << formatting
		if start > self._maxpos:
			self._positions.append(start)
			self._formatting.append(effect)
			self._positions.append(end)
			self._formatting.append(effect)
			self._maxpos = end
			return
		i = 0
		while start > self._positions[i]:
			i += 1
		if self._positions[i] == start:	#if we're writing into a number
			self._formatting[i] |= effect
		else:
			self._positions.insert(i,start)
			self._formatting.insert(i,effect)
		i += 1

		while i < len(self._positions) and end > self._positions[i]:
			if self._formatting[i] & effect: #if this effect turns off here
				self._formatting[i] ^= effect
			i += 1
		if end > self._maxpos:
			self._positions.append(end)
			self._formatting.append(effect)
			self._maxpos = end
		#position exists
		elif self._positions[i] == end:
			self._formatting[i] |= effect
		else:
			self._positions.insert(i,end)
			self._formatting.insert(i,effect)

	def addGlobalEffect(self, effectNumber,pos = 0):
		'''Add effect to string'''
		self.effectRange(pos,len(self._str),effectNumber)

	def findColor(self, end):
		'''Most recent color before end. Safe when no matches are found'''
		if self._maxpos == -1:
			return None
		if end > self._maxpos:
			return self._formatting[-1]
		last = self._formatting[0]
		for pos,form in zip(self._positions,self._formatting):
			if end < pos:
				return last
			last = form
		return last

	def colorByRegex(self, regex, groupFunction, fallback = None, group = 0):
		'''
		Color from a compiled regex, generating the respective color number
		from captured group. groupFunction should be an int or callable that
		returns int
		'''
		if not callable(groupFunction):
			ret = groupFunction	#get another header
			groupFunction = lambda x: ret
		#only getLast when supplied a color number fallback
		getLast = False
		if isinstance(fallback, int):
			getLast = True

		for find in regex.finditer(self._str+' '):
			begin = find.start(group)
			end = find.end(group)
			#insert the color
			if getLast:
				#find the most recent color
				last = self.findColor(begin)
				last = last is None and fallback or last
				self.insertColor(begin,groupFunction(find.group(group)))
				self._insertColor(end,last) #backend because last is already valid
			else:
				self.insertColor(begin,groupFunction(find.group(group)))
	def effectByRegex(self, regex, effect, group = 0):
		for find in regex.finditer(self._str+' '):
			self.effectRange(find.start(group),find.end(group),effect)

	def breaklines(self,length,outdent=""):
		'''Break string (courteous of spaces) into a list of column-length 'length' substrings'''
		outdentLen = strlen(outdent)
		TABSPACE = length - outdentLen
		THRESHOLD = length >> 1
		broken = []

		start = 0
		space = length
		lineBuffer = ""

		formatPos = 0
		getFormat = bool(len(self._positions))
		lastColor = 0
		lastEffect = 0
		for pos,j in enumerate(self._str):	#character by character, the old fashioned way
			lenj = wcwidth(j)
			if getFormat and pos == self._positions[formatPos]:
				lineBuffer += self._str[start:pos]
				start = pos
				lastColor = (self._formatting[formatPos] >> _NUM_EFFECTS) or lastColor
				nextEffect = self._formatting[formatPos] & _EFFECTS_BITS
				formatPos += 1
				getFormat = formatPos != len(self._positions)
				if space > 0:
					lineBuffer += lastColor > 0 and _COLORS[lastColor-1] or ""
					for i in range(_NUM_EFFECTS):
						if ((1 << i) & nextEffect):
							if ((1 << i) & lastEffect):
								lineBuffer += _EFFECTS[i][1]
							else:
								lineBuffer += _EFFECTS[i][0]
				lastEffect ^= nextEffect
			if j == '\t':			#tabs are the length of outdents
				lenj = outdentLen
				lineBuffer += self._str[start:pos]
				start = pos+1 #skip over tab
				lineBuffer += ' '*min(lenj,space)
			elif j == '\n':
				lineBuffer += self._str[start:pos]
				if lineBuffer.rstrip() != outdent.rstrip():
					broken.append(lineBuffer + CLEAR_FORMATTING)
				lineBuffer = outdent
				lineBuffer += lastColor > 0 and _COLORS[lastColor-1] or ""
				for i in range(_NUM_EFFECTS):
					if lastEffect & (1 << i):
						lineBuffer += _EFFECTS[i][0]
				start = pos+1 #skip over newline
				lastcol = 0
				space = TABSPACE
				continue
			elif ord(j) < 32:		#other non printing
				continue

			space -= lenj
			if j in _LINE_BREAKING and space > 0: #add the last word
				lineBuffer += self._str[start:pos+1]
				start = pos+1
				lastcol = space
			if space <= 0:			#time to break
				if lastcol < THRESHOLD and lastcol > 0:
					broken.append(lineBuffer + CLEAR_FORMATTING)
					lineBuffer = outdent
					lineBuffer += lastColor > 0 and _COLORS[lastColor-1] or ""
					for i in range(_NUM_EFFECTS):
						if lastEffect & (1 << i):
							lineBuffer += _EFFECTS[i][0]
					lenj += lastcol
				else:
					broken.append("{}{}{}".format(lineBuffer,self._str[start:pos],CLEAR_FORMATTING))
					lineBuffer = outdent
					lineBuffer += lastColor > 0 and _COLORS[lastColor-1] or ""
					for i in range(_NUM_EFFECTS):
						if lastEffect & (1 << i):
							lineBuffer += _EFFECTS[i][0]
					start = pos
				lastcol = 0
				space = TABSPACE - lenj

		lineBuffer += self._str[start:]
		if lineBuffer.rstrip() != outdent.rstrip():
			broken.append(lineBuffer+CLEAR_FORMATTING)

		return broken,len(broken)

def strlen(string):
	'''Column width of a string'''
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

def columnslice(string,length):
	'''Fit string to column width'''
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

class Scrollable:
	'''Scrollable text input'''
	def __init__(self,width,string=""):
		self._str = string
		self._width = width
		self._pos = len(string)
		self._disp = max(0,len(string)-width)
		#nonscrolling characters
		self._nonscroll = ""
		self._nonscroll_width = 0
		self.password = False;
	def __repr__(self):
		return repr(self._str)
	def __str__(self):
		'''Return the raw text contained'''
		return self._str
	def __getitem__(self,sliced):
		'''Get a slice up to the cursor'''
		newstop = sliced.stop
		if not sliced.stop: newstop = self._pos
		else: newstop = min(newstop,self._pos)
		return self._str[slice(sliced.start,newstop,sliced.step)]
	def __format__(self,*args):
		'''Display text contained with cursor'''
		#original string injections
		text = ""
		if self.password:
			text = '*'*(self._pos) + CHAR_CURSOR + '*'*(len(self._str)-self._pos)
		else:
			text = self._str[:self._pos] + CHAR_CURSOR + self._str[self._pos:]
	
		text = text[self._disp:self._disp+self._width+len(CHAR_CURSOR)] #worst case
		text = text.replace("\n",r"\n").expandtabs(_TABLEN)
		#TIME TO ITERATE
		escape,canbreak= 0,0
		#initial position, column num, position in string
		init,width,pos= 0,self._nonscroll_width,0
		#_disp is never greater than _pos, and it's impossible for 
		#"s" to not be in a control sequence, so this should be sound
		while pos < len(text) or not canbreak:
			i = text[pos]
			temp = (i == '\x1b') or escape
			if not temp:
				width += wcwidth(i)
				if width >= self._width:
					if canbreak: #don't go too far
						break
					init += 1
			elif i.isalpha():	#is escaped and i is alpha
				if i == 's':	#\x1b[s is save cursor position; if we go past it, great
					canbreak = True
				temp = False
			pos += 1
			escape = temp
		return self._nonscroll+text[init:pos]
	#str-like frontends
	def find(self,string,start=0,end=None):
		'''Find up to cursor position'''
		if end is None:
			end = self._pos
		return self._str.find(string,start,end)
	def rfind(self,string,start=0,end=None):
		'''Right find up to cursor position'''
		if end is None:
			end = self._pos
		return self._str.rfind(string,start,end)
	def complete(self):
		'''Complete the last word before the cursor'''
		lastSpace = self._str.rfind(" ",0,self._pos)
		#if there is no lastspace, settle for 0
		search = self._str[lastSpace+1:self._pos]
		if lastSpace == -1: search = self._nonscroll + search
		ret = Tokenize.complete(search)
		if ret:
			self.append(ret + " ")
		
	#-----------------
	def _onchanged(self):
		'''
		Since this class is meant to take a 'good' slice of a string,
		it's useful to have this method when that slice is updated
		'''
		pass
	def setstr(self,new):
		'''Set content of scrollable'''
		self._str = new
		self.end()
	def setnonscroll(self,new):
		'''Set nonscrolling characters of scrollable'''
		check = strlen(new)
		if check > MAX_NONSCROLL_WIDTH:
			new = new[:columnslice(new,MAX_NONSCROLL_WIDTH)]
		self._nonscroll = new
		self._nonscroll_width = min(check,MAX_NONSCROLL_WIDTH)
		self._onchanged()
	def setwidth(self,new):
		if new is None: return
		if new <= 0:
			raise DisplayException()
		self._width = new
		self._onchanged()
	def movepos(self,dist):
		'''Move cursor by distance (can be negative). Adjusts display position'''
		if not len(self._str):
			self._pos,self._disp = 0,0
			self._onchanged()
			return
		self._pos = max(0,min(len(self._str),self._pos+dist))
		curspos = self._pos - self._disp
		if curspos <= 0: #left hand side
			self._disp = max(0,self._disp+dist)
		elif (curspos+1) >= self._width: #right hand side
			self._disp = min(self._pos-self._width+1,self._disp+dist)
		self._onchanged()
			
	def append(self,new):
		'''Append string at cursor'''
		self._str = self._str[:self._pos] + new + self._str[self._pos:]
		self.movepos(len(new))
	def backspace(self):
		'''Backspace one char at cursor'''
		if not self._pos: return #don't backspace at the beginning of the line
		self._str = self._str[:self._pos-1] + self._str[self._pos:]
		self.movepos(-1)
	def delchar(self):
		'''Delete one char ahead of cursor'''
		self._str = self._str[:self._pos] + self._str[self._pos+1:]
		self._onchanged()
	def delword(self):
		'''Delete word behind cursor, like in sane text boxes'''
		pos = _UP_TO_WORD_RE.match(' '+self._str[:self._pos])
		if pos and not self.password:
			#we started with a space
			span = pos.span(1)[1] - 1
			#how far we went
			self._str = self._str[:span] + self._str[self._pos:]
			self.movepos(span-self._pos)
		else:
			self._str = self._str[self._pos:]
			self._disp = 0
			self._pos = 0
			self._onchanged()
	def clear(self):
		'''Clear cursor and string'''
		self._str = ""
		self.home()
	def home(self):
		'''Return to the beginning'''
		self._pos = 0
		self._disp = 0
		self._onchanged()
	def end(self):
		'''Move to the end'''
		self._pos = 0
		self._disp = 0
		self.movepos(len(self._str))

class Tokenize:
	'''Class for holding new tab-completers'''
	prefixes = []			#list of prefixes to search for
	suggestionlists = []	#list of (references to) lists for each prefix paradigm
	def __init__(self,newPrefix,newList,ignore=None):
		'''Add a new tabbing method'''
		self.prefixes.append(newPrefix)
		self.suggestionlists.append(newList)
	
	def complete(incomplete):
		'''Find rest of a name in a list'''
		#O(|prefixes|*|suggestionlists|), so n**2
		for pno,prefix in enumerate(Tokenize.prefixes):
			preflen = len(prefix)
			if (incomplete[:preflen] == prefix):
				search = incomplete[preflen:]
				#search for the transformed search
				for complete in list(Tokenize.suggestionlists[pno]):
					#run the transforming lambda
					if not complete.find(search):	#in is bad practice
						return complete[len(incomplete)-1:]
				return ""
		return ""

class PromoteSet:
	'''Set with ordering like a list, whose elements can be promoted to the front'''
	def __init__(self,iterable = None):
		self._list = list()
		if iterable is not None:
			for i in iterable:
				self.append(i)
	def __repr__(self):
		return "promoteSet({})".format(repr(self._list))
	def __iter__(self):
		return iter(self._list)
	def __len__(self):
		return len(self._list)
	
	def append(self,new):
		'''Add an item to the list'''
		if new in self._list: return
		self._list.append(new)
	def extend(self,iterable):
		'''Append each element in iterable'''
		for i in iterable:
			self.append(i)
	def clear(self):
		'''Clear list'''
		self._list.clear()
	def remove(self,old):
		'''Remove an item from the list'''
		if old not in self._list: raise KeyError(old)
		self._list.remove(old)
	def promote(self,index):
		'''Promote index to the front of the list'''
		if len(self._list) < 2: return
		i = 1
		found = False
		#look for the value
		while i <= len(self._list):
			if self._list[-i] == index:
				found = True
				break
			i += 1
		if not found: raise KeyError(index)
		if i == len(self._list): return
		#swap successive values
		while i < len(self._list):
			temp = self._list[-i-1] 
			self._list[-i-1] = self._list[-i]
			self._list[-i] = temp
			i += 1
