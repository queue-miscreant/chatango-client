#!/usr/bin/env python3
#client.display.py
'''
Module for formatting; support for fitting strings to column
widths and ANSI color escape string manipulations. Also contains
generic string containers.
'''
import re
from shlex import shlex
from .wcwidth import wcwidth

#all imports needed by overlay.py
__all__ =	["CLEAR_FORMATTING","CHAR_CURSOR","SELECT"
			,"_COLORS","SELECT_AND_MOVE","dbmsg","def256colors","getColor","rawNum"
			,"collen","Coloring","Scrollable","Tokenize","ScrollSuggest"]

#REGEXES------------------------------------------------------------------------
_SANE_TEXTBOX =		r"\s\-/`~,;"			#sane textbox splitting characters
_LAST_COLOR_RE =	re.compile('\x1b'+r"\[[^m]*3[^m]*m")	#find last color inserted (contains a 3)
_UP_TO_WORD_RE =	re.compile("([^{0}]*[{0}])*[^{0}]+[{0}]*".format(_SANE_TEXTBOX))	#sane textbox word-backspace
_NEXT_WORD_RE =	re.compile("([{0}]*[^{0}]+)".format(_SANE_TEXTBOX))	#sane textbox word-delete
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

def defColor(fore,back = "none",intense = False):
	'''Define a new foreground/background pair, with optional intense color'''
	global _COLORS
	pair = "\x1b[3"
	if isinstance(fore,int):
		pair += "8;5;%d" % fore;
	else:
		pair += str(_COLOR_NAMES.index(fore));
		pair += intense and ";1" or ";22"
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
		return "Coloring({}, positions = {}, formatting = {})".format(
			repr(self._str),self._positions,self._formatting)
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
		if start < 0: start = len(self._str) + start
		if end < 0: end = len(self._str) + end
		if start > end and not end: end = len(self._str) #shortcut
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

		for find in regex.finditer(self._str):
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
		'''
		Break string (courteous of spaces) into a list of strings spanning
		up to `length` columns
		'''
		outdentLen = collen(outdent)
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
			#if we have a 'next color', and we're at that position
			if getFormat and pos == self._positions[formatPos]:
				lineBuffer += self._str[start:pos]
				start = pos
				#decode the color/effect
				lastColor = (self._formatting[formatPos] >> _NUM_EFFECTS) or lastColor
				nextEffect = self._formatting[formatPos] & _EFFECTS_BITS
				formatPos += 1
				getFormat = formatPos != len(self._positions)
				#do we even need to draw this?
				if space > 0:
					lineBuffer += lastColor > 0 and _COLORS[lastColor-1] or ""
					for i in range(_NUM_EFFECTS):
						if ((1 << i) & nextEffect):
							if ((1 << i) & lastEffect):
								lineBuffer += _EFFECTS[i][1]
							else:
								lineBuffer += _EFFECTS[i][0]
				#effects are turned off and on by the same bit
				lastEffect ^= nextEffect
			if j == '\t':			#tabs are the length of outdents
				lenj = outdentLen
				lineBuffer += self._str[start:pos]
				start = pos+1 #skip over tab
				lineBuffer += ' '*min(lenj,space)
			elif j == '\n':
				#add the new line
				lineBuffer += self._str[start:pos]
				if lineBuffer.rstrip() != outdent.rstrip():
					broken.append(lineBuffer + CLEAR_FORMATTING)
				#refresh variables
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
			#if this is a line breaking character and we have room just after it
			if j in _LINE_BREAKING and space > 0:
				#add the last word
				lineBuffer += self._str[start:pos+1]
				start = pos+1
				lastcol = space
			if space <= 0:			#time to break
				#do we have a 'last space (breaking char)' recent enough to split after?
				if lastcol < THRESHOLD and lastcol > 0:
					broken.append(lineBuffer + CLEAR_FORMATTING)
					lineBuffer = outdent
					lineBuffer += lastColor > 0 and _COLORS[lastColor-1] or ""
					for i in range(_NUM_EFFECTS):
						if lastEffect & (1 << i):
							lineBuffer += _EFFECTS[i][0]
					lenj += lastcol
				#split on a long word
				else:
					broken.append(lineBuffer + self._str[start:pos] + CLEAR_FORMATTING)
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

def collen(string):
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

class Scrollable:
	'''Scrollable text input'''
	def __init__(self,width,string=""):
		if width <= _TABLEN:
			raise DisplayException("Cannot create Scrollable smaller "+\
				" or equal to tab width %d"%_TABLEN)
		self._str = string
		self._width = width
		#position of the cursor and display column of the cursor
		self._pos = len(string)
		self._disp = max(0,collen(string)-width)
		#nonscrolling characters
		self._nonscroll = ""
		self._nonscroll_width = 0
		self.password = False
	def __repr__(self):
		return repr(self._str)
	def __str__(self):
		'''Return the raw text contained'''
		return self._str
	def __format__(self,*args):
		'''Display text contained with cursor'''
		#iteration variables
		start, end, width = self._disp, self._disp, self._nonscroll_width
		#handle the first test already, +1 for truth values
		endwidth = (end == self._pos) and width+1
		lentext = len(self._str)
		#adjust the tail
		while not endwidth or (width < self._width and end < lentext):
			char = self._str[end]
			if char == '\t':
				width += _TABLEN
			elif char == '\n' or char == '\r':
				width += 2	#for r'\n'
			elif ord(char) >= 32:
				width += wcwidth(char)
			end += 1
			if end == self._pos:
				endwidth = width+1
		#adjust the head
		while width >= self._width:
			char = self._str[start]
			if char == '\t':
				width -= _TABLEN
			elif char == '\n' or char == '\r':
				width -= 2	#for \n
			elif ord(char) >= 32:
				width -= wcwidth(char)
			start += 1
		if self.password:
			if not endwidth: #cursor is at the end
				endwidth = self._width
			else:
				endwidth -= 1
			return "%s%s%s%s"%(self._nonscroll,'*'*endwidth,CHAR_CURSOR,
				'*'*(width-endwidth))
		text = "%s%s%s%s"%(self._nonscroll,self._str[start:self._pos],
			CHAR_CURSOR,self._str[self._pos:end])
		#actually replace the lengths I asserted earlier
		return text.replace('\n','\\n').replace('\r',
			'\\r').replace('\t',' '*_TABLEN)
	#SET METHODS----------------------------------------------------------------
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
		check = collen(new)
		if check > MAX_NONSCROLL_WIDTH:
			new = new[:columnslice(new,MAX_NONSCROLL_WIDTH)]
		self._nonscroll = new
		self._nonscroll_width = min(check,MAX_NONSCROLL_WIDTH)
		self._onchanged()
	def setwidth(self,new):
		'''Set width of the scrollable'''
		if new <= 0:
			raise DisplayException()
		self._width = new
		self._onchanged()
	#TEXTBOX METHODS-----------------------------------------------------------
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
	def wordback(self):
		'''Go back to the last word'''
		pos = _UP_TO_WORD_RE.match(' '+self._str[:self._pos])
		if pos and not self.password:
			#_UP_TO_WORD_RE captures a long series of words
			#from the start. where it ends is how far we go.
			#move backward, so subtract the larger position, offset of 1 b/c space
			self.movepos(pos.end(1)-self._pos-1)
		else:
			self.home()
	def wordnext(self):
		'''Advance to the next word'''
		pos = _NEXT_WORD_RE.match(self._str[self._pos:]+' ')
		if pos and not self.password:
			span = (lambda x: x[1] - x[0])(pos.span(1))
			self.movepos(span)
		else:
			self.end()
	#CHARACTER INSERTION--------------------------------------------------------
	def append(self,new):
		'''Append string at cursor'''
		self._str = self._str[:self._pos] + new + self._str[self._pos:]
		self.movepos(len(new))
	#CHARACTER DELETION METHODS-------------------------------------------------
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
			span = pos.end(1) - 1
			#how far we went
			self._str = self._str[:span] + self._str[self._pos:]
			self.movepos(span-self._pos)
		else:
			self._str = self._str[self._pos:]
			self._disp = 0
			self._pos = 0
			self._onchanged()
	def delnextword(self):
		'''Delete word ahead of cursor, like in sane text boxes'''
		pos = _NEXT_WORD_RE.match(self._str[self._pos:]+' ')
		if pos and not self.password:
			span = pos.end(1)
			#how far we went
			self._str = self._str[:self._pos] + self._str[self._pos+span:]
		else:
			self._str = self._str[:self._pos]
		self._onchanged()
	def clear(self):
		'''Clear cursor and string'''
		self._str = ""
		self.home()
	def undo(self):
		#TODO populate a list of changes since some interval
		#or after pressing space
		pass

class Tokenize:
	'''Class for holding new tab-completers'''
	prefixes = []		#list of prefixes to search for
	suggestions = []	#list of (references to) lists for each prefix paradigm
	def __init__(self,newPrefix=None,newSuggest=None):
		'''Add a new tabbing method'''
		if newPrefix is None and newSuggest is None:
			self.localPrefix = []
			self.localSuggest = []
			self.complete = lambda x: Tokenize.complete(x,self)
			return
		elif newPrefix is None or newSuggest is None:
			raise DisplayException("Invalid number of arguments for Tokenize. "+\
				"Must be 0 args for instance, or 2 args for global class")
		self.prefixes.append(newPrefix)
		self.suggestions.append(newSuggest)

	def addComplete(self,newPrefix,newSuggest):
		'''Add new completion token to the class'''
		self.localPrefix.append(newPrefix)
		self.localSuggest.append(newSuggest)
	
	@classmethod
	def complete(cls,incomplete,self=None):
		'''Find rest of a name in a list'''
		if isinstance(self,cls):
			#go through the local lists first
			ret = cls._complete(incomplete,self.localPrefix,self.localSuggest)
			if ret:	#don't cut off all completions
				return ret
		return cls._complete(incomplete,cls.prefixes,cls.suggestions)

	@staticmethod
	def _complete(incomplete,prefixes,suggestions):
		'''Backend for complete'''
		#O(|prefixes|*|suggestionlists|), so n**2
		for pno,prefix in enumerate(prefixes):
			preflen = len(prefix)
			if (incomplete[:preflen] == prefix):
				search = incomplete[preflen:]
				return Tokenize.collapseSuggestion(search,suggestions[pno])[0]
		return []

	@staticmethod
	def collapseSuggestion(search,suggestion,addSpace=True):
		'''
		When a list of suggestions (or a callable that generates them) has
		been found, cut the list down based on the length of the search
		'''
		cut = len(search)
		truecut = 0
		if callable(suggestion):
			suggest,cut = suggestion(search)
			if cut < 0:
				truecut = cut
				cut = 0
		else:
			suggest = [i for i in list(suggestion) if not i.find(search)]

		if addSpace:
			addSpace = ' '
		else:
			addSpace = ''

		return [i[cut:]+addSpace for i in suggest], truecut
			

class ScrollSuggest(Scrollable):
	'''
	A Scrollable extension with suggestion built in
	If you need to extend a Scrollable, it's probably this one
	'''
	def __init__(self,width,string=""):
		super(ScrollSuggest,self).__init__(width,string)
		self._argumentComplete = {}
		#completer
		self.completer = Tokenize()
		self._suggestList = []
		self._suggestNum = 0
		self._keepSuggest = False
		#storage vars
		self._lastdisp = None
		self._lastpos = None
	def addCommand(self,command,suggestion):
		self._argumentComplete[command] = suggestion
	def complete(self):
		'''Complete the last word before the cursor'''
		#need to generate list
		if not self._suggestList:
			closeQuote = False
			if self._str[:self._pos].count('"') % 2:
				lexicon = shlex(self._str[:self._pos]+'"',posix=True)
				closeQuote = True
			else:
				lexicon = shlex(self._str[:self._pos],posix=True)
			lexicon.quotes = '"' #no single quotes
			lexicon.wordchars += ''.join(self.completer.localPrefix) + \
				''.join(self.completer.prefixes) + '/~' #add in predefined characters
			#TODO go back to old method
			argsplit = []
			lastToken = lexicon.get_token()
			while lastToken:
				argsplit.append(lastToken)
				lastToken = lexicon.get_token()

			if len(argsplit) > 1 and self._argumentComplete:
				verb, suggest = argsplit[0], argsplit[-1]
				if verb in self._argumentComplete:
					complete = self._argumentComplete[verb]
					tempSuggest, temp = Tokenize.collapseSuggestion(argsplit[-1],
						complete,addSpace=False)
					if tempSuggest and temp:
						#-2 for both quotes being counted
						startedWithQuote = self._str[-len(argsplit[-1])-2] == '"'
						if startedWithQuote or closeQuote:
							#if we're closing a quote, then we only need to account
							#for one quote
							temp -= 1 + (not closeQuote)
							tempSuggest = [(i[-1] != '"') and ('"%s"' % i) or i
								for i in tempSuggest]
							
						self._str = self._str[:self._pos+temp] + self._str[self._pos:]
						self.movepos(temp)
						self._suggestList = tempSuggest

			#just use a prefix
			if len(argsplit) > 0 and not self._suggestList:
				search = argsplit[-1]
				if self._str[self._pos-1:self._pos] == ' ':
					#no need to try to complete if there's a space after the word
					return
				if len(argsplit) == 1: search = self._nonscroll + search
				self._suggestList = self.completer.complete(search)

		#if there's a list or we could generate one
		if self._suggestList:
			self._suggestNum = (self._suggestNum+1)%len(self._suggestList)
			suggestion = self._suggestList[self._suggestNum]
			#no need to tab through a single one
			if len(self._suggestList) > 1:
				self._keepSuggest = True
				if self._lastpos is None:
					self._lastpos,self._lastdisp = self._pos,self._disp
				else:
					self._str = self._str[:self._lastpos] + self._str[self._pos:]
					self._pos,self._disp = self._lastpos,self._lastdisp
			self.append(suggestion)
			return True
	def backcomplete(self):
		'''Complete, but backwards. Assumes already generated list'''
		if self._suggestList:
			self._suggestNum = (self._suggestNum-1)%len(self._suggestList)
			suggestion = self._suggestList[self._suggestNum]
			self._keepSuggest = True
			if self._lastpos is None:
				self._lastpos,self._lastdisp = self._pos,self._disp
			else:
				self._str = self._str[:self._lastpos] + self._str[self._pos:]
				self._pos,self._disp = self._lastpos,self._lastdisp
			self.append(suggestion)
			return True
	def _onchanged(self):
		'''Get rid of stored suggestions'''
		if not self._keepSuggest:
			self._suggestNum = -1
			self._suggestList.clear()
			self._lastpos,self._lastdisp = None,None
		self._keepSuggest = False
