#!/usr/bin/env python3
#client.display.py
'''Module for formatting; support for fitting strings to column
widths and ANSI color escape string manipulations. Also contains
generic string containers.'''
#TODO	breaklines built into coloring
#TODO	256-bit mode to define colors in 256 bits
import re
from .wcwidth import wcwidth

#DEBUG STUFF--------------------------------------------------------------------
def dbmsg(*args):
	'''Since the client runs in a contained curses session, printing more '''+\
	'''is out of the question. So just print to file 'debug' '''
	with open("debug","a+") as a:
		for i in args:
			a.write(str(i)+"\t")
		a.write("\n")
		a.close()

#REGEXES------------------------------------------------------------------------
_SANE_TEXTBOX = r'\s\-/`~,;'			#sane textbox splitting characters
_ANSI_ESC_RE = re.compile("\x1b"+r"\[[^A-z]*[A-z]")		#general ANSI escape
_LAST_COLOR_RE =	re.compile("\x1b"+r"\[[^m]*3[^m]*m")	#find last color inserted (contains a 3)
_LAST_EFFECT_RE =	re.compile("\x1b"+r"\[2?[47]m")			#all effects that are on
_UP_TO_WORD_RE = re.compile('([^{0}]*[{0}])*[^{0}]+[{0}]*'.format(_SANE_TEXTBOX))	#sane textbox word-backspace
_LINE_BREAKING = " 　"
#valid color names to add
_COLOR_NAMES =	['black'
				,'red'
				,'green'
				,'yellow'
				,'blue'
				,'magenta'
				,'cyan'
				,'white'
				,''
				,'none']
#names of effects, and a tuple containing 'on' and 'off'
_EFFECTS =	{'reverse':		('\x1b[7m','\x1b[27m')
			,'underline':	('\x1b[4m','\x1b[24m')
			}
#storage for defined pairs
_COLORS =	['\x1b[39;49m'	#Normal/Normal
			,'\x1b[31;47m'	#Red/White
			,'\x1b[31;41m'	#red
			,'\x1b[32;42m'	#green
			,'\x1b[34;44m'	#blue
			]
_NUM_PREDEFINED = len(_COLORS)
#clear formatting
CLEAR_FORMATTING = '\x1b[m'
SELECTED = lambda x: _EFFECTS['reverse'][0] + x + CLEAR_FORMATTING
CHAR_CURSOR = '\x1b[s'
_TABLEN = 4
#arbitrary number of characters a scrollable can have and not scroll
MAX_NONSCROLL_WIDTH = 5

class FormattingException(Exception):
	'''Exception for client.termform'''
	pass

def defColor(fore, bold = None, back = 'none'):
	'''Define a new foreground/background pair, with optional intense color'''
	global _COLORS
	pair = '\x1b[3%d' % _COLOR_NAMES.index(fore);
	pair += bold and ";1" or ";22"
	pair += ';4%d' % _COLOR_NAMES.index(back)
	_COLORS.append(pair+'m')

def getColor(c):
	'''insertColor without position or coloring object'''
	if c == None: return ''
	try:
		return _COLORS[c + _NUM_PREDEFINED]
	except IndexError:
		raise FormattingException("Color definition %d not found"%c)

def rawNum(c):
	'''Get raw pair number, without respect for number of predefined ones. '''+\
	'''Use in conjunction with getColor (or insertColor) to use predefined colors'''
	return c - _NUM_PREDEFINED

def getEffect(effect):
	'''Get effect. Raise exception when undefined'''
	try:
		return _EFFECTS[effect]
	except KeyError:
		raise FormattingException("Effect name %s not defined"%effect)

def decolor(string):
	'''Replace all ANSI escapes with null string'''
	new = _ANSI_ESC_RE.subn('',string)
	return new[0]

class coloringold:
	'''Container for a string and default color'''
	def __init__(self,string,default=None):
		self._str = string
		self.default = default
	def __str__(self):
		'''Colorize the string'''
		return self._str
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
		return self
	def insertColor(self,p,c=None):
		'''Add a color at position p with color c'''
		c = self.default if c is None else c
		if type(c) is int: c = getColor(c)
		self._str =  self._str[:p] + c + self._str[p:]
		#return amount added to string
		return len(c)
	def addGlobalEffect(self, effect):
		'''Add effect to string'''
		effect = getEffect(effect)
		self._str = effect[0] + self._str
		#take all effect offs out
		self._str = self._str.replace(effect[1],'')
	def findColor(self,end):
		'''Most recent color before end. Safe when no matches are found'''
		lastcolor = {end-i.end(0):i.group(0) for i in \
			 _LAST_COLOR_RE.finditer(self._str) if (end-i.end(0))>=0}
		try:
			return lastcolor[min(lastcolor)]
		except:
			return ''
	def colorByRegex(self, regex, groupFunction, group = 0, post = None):
		'''Color from a compiled regex, generating the respective color number from captured group. '''+\
		'''groupFunction should be an int (or string) or callable that returns int (or string)'''
		if not callable(groupFunction):
			ret = groupFunction	#get another header
			groupFunction = lambda x: ret
		tracker = 0
		for find in regex.finditer(str(self)+' '):
			#we're iterating over the 'past string' so we need to preserve
			#previous iterations
			begin = tracker+find.start(group)
			#find the most recent color
			last = self.findColor(begin)
			#insert the color
			tracker += self.insertColor(begin,groupFunction(find.group(group)))
			end = tracker+find.end(group)
			#insert the end color and adjust the tracker (if we're conserving color)
			tracker += (post is None) and self.insertColor(end,last) or self.insertColor(end,post)
	def effectByRegex(self, regex, effect, group = 0):
		effect = getEffect(effect)
		self.colorByRegex(regex,lambda x: effect[0],group,effect[1])

class coloring:
	'''Container for a string and default color'''
	def __init__(self,string,default=None):
		self._str = string
		self.default = default
		self.positions = []
		self.formatting = []
		self.maxpos = -1
	def __repr__(self):
		'''Get the string contained'''
		return "coloring({}, positions = {}, formats = {})".format(repr(self._str),self.positions,self.formatting)
	def __str__(self):
		'''Colorize the string'''
		ret = self._str
		tracker = 0
		for pos,form in zip(self.positions,self.formatting):
			ret = ret[:pos+tracker] + form + ret[pos+tracker:]
			tracker += len(form)
		return ret
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
		for pos,i in enumerate(self.positions):
			self.positions[pos] = i + len(other)
		return self
	def insertColor(self,position,formatting=None):
		'''Insert positions/formatting into color dictionary'''
		if position < 0: position += len(self._str);
		formatting = self.default if formatting is None else formatting
		if type(formatting) is int: formatting = getColor(formatting)
		if position > self.maxpos:
			self.positions.append(position)
			self.formatting.append(formatting)
			self.maxpos = position
			return
		i = 0
		while position > self.positions[i]:
			i += 1
		if self.positions[i] == position:		#position already used
			self.formatting[i] += formatting
		else:
			self.positions.insert(i,position)
			self.formatting.insert(i,formatting)

	def addGlobalEffect(self, effect):
		'''Add effect to string'''
		effect = getEffect(effect)
		self.insertColor(0,effect[0])
		#take all effect offs out
		for pos,i in enumerate(self.formatting):
			self.formatting[pos] = i.replace(effect[1],'')

	def findColor(self,end):
		'''Most recent color before end. Safe when no matches are found'''
		if end > self.positions[-1]:
			return self.formatting[-1]
		last = ''
		for pos,form in zip(self.positions,self.formatting):
			if end < pos:
				return last
			last = form
	def colorByRegex(self, regex, groupFunction, group = 0, post = None):
		'''Color from a compiled regex, generating the respective color number from captured group. '''+\
		'''groupFunction should be an int (or string) or callable that returns int (or string)'''
		if not callable(groupFunction):
			ret = groupFunction	#get another header
			groupFunction = lambda x: ret
		for find in regex.finditer(self._str+' '):
			begin = find.start(group)
			end = find.end(group)
			#insert the color
			#if there's no post-effect, conserve the last color
			if post is None:
				#find the most recent color
				last = self.findColor(begin)
				self.insertColor(begin,groupFunction(find.group(group)))
				self.insertColor(end,last)
			else:
				self.insertColor(begin,groupFunction(find.group(group)))
				#useful for turning effects off
				self.insertColor(end,post)
	def effectByRegex(self, regex, effect, group = 0):
		effect = getEffect(effect)
		self.colorByRegex(regex,lambda x: effect[0],group,effect[1])

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

def breaklines(string,length,outdent=''):
	'''Break string (courteous of spaces) into a list of column-length 'length' substrings'''
	string = string.expandtabs(_TABLEN)
	outdentLen = strlen(outdent)
	TABSPACE = length - outdentLen
	THRESHOLD = length/2

	broken = []
	form = ''
	for i,line in enumerate(string.split("\n")):
		start = 0
		lastbreaking,lastcol = 0,0
		color,effect = '',''
		space = (i and TABSPACE) or length
		escapestart = 0
		for pos,j in enumerate(line):	#character by character, the old fashioned way
			if escapestart:
				if j.isalpha():
					sequence = line[escapestart-1:pos+1]
					if _LAST_COLOR_RE.match(sequence):
						color = sequence
					elif j == 'm':			#sequence ending in m that isn't a color is an effect
						effect += sequence
					escapestart = 0
				continue
			elif j == "\x1b":
				escapestart = pos+1			#sequences at 0 are okay
				continue

			lenj = wcwidth(j)
			space -= lenj
			if j in _LINE_BREAKING:
				lastbreaking = pos
				lastcol = space
			if space < 0:			#time to break
				if lastcol < THRESHOLD and lastbreaking > start:
					broken.append("{}{}{}".format(form,line[start:lastbreaking],CLEAR_FORMATTING))
					start = lastbreaking+1	#ignore whitespace
					lenj += lastcol
				else:
					broken.append("{}{}{}".format(form,line[start:pos],CLEAR_FORMATTING))
					start = pos
				space = TABSPACE - lenj
				form = outdent + color + effect

		broken.append("{}{}{}".format(form,line[start:],CLEAR_FORMATTING))
		form = outdent + color + effect

	return broken,len(broken)

class scrollable:
	'''Scrollable text input'''
	def __init__(self,width,string=''):
		self._str = string
		self._width = width
		self._pos = len(string)
		self._disp = max(0,len(string)-width)
		#nonscrolling characters
		self._nonscroll = ''
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
		ret = tabber.complete(search)
		if ret:
			self.append(ret + " ")
		
	#-----------------
	def _onchanged(self):
		'''Since this class is meant to take a 'good' slice of a string,'''+\
		''' It's useful to have this method when that slice is updated'''
		pass
	def setstr(self,new):
		self._str = new
		self.end()
	def setnonscroll(self,new):
		check = strlen(new)
		if check > MAX_NONSCROLL_WIDTH:
			new = new[:columnslice(new,MAX_NONSCROLL_WIDTH)]
		self._nonscroll = new
		self._nonscroll_width = min(check,MAX_NONSCROLL_WIDTH)
		self._onchanged()
	def setwidth(self,new):
		if new is None: return
		if new <= 0:
			raise FormattingException()
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

class tabber:
	'''Class for holding new tab-completers'''
	prefixes = []			#list of prefixes to search for
	fittinglambdas = []		#functions that take an incomplete argument and transform it to something in the list
	suggestionlists = []	#list of (references to) lists for each prefix paradigm
	def __init__(self,newPrefix,newList,ignore=None):
		'''Add a new tabbing method'''
		self.prefixes.append(newPrefix)
		self.suggestionlists.append(newList)
		self.fittinglambdas.append(ignore)
	
	def complete(incomplete):
		'''Find rest of a name in a list'''
		#O(|prefixes|*|suggestionlists|), so n**2
		for pno,prefix in enumerate(tabber.prefixes):
			preflen = len(prefix)
			if (incomplete[:preflen] == prefix):
				istransformed = bool(callable(tabber.fittinglambdas[pno]))
				search = incomplete[preflen:]
				#search for the transformed search
				for complete in list(tabber.suggestionlists[pno]):
					#run the transforming lambda
					if istransformed: complete = tabber.fittinglambdas[pno](complete)
					if not complete.find(search):	#in is bad practice
						return complete[len(incomplete)-1:]
				return ""
		return ""

class promoteSet:
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
