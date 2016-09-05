#!/usr/bin/env python3
#client.display.py
'''Module for formatting; support for fitting strings to column
widths and ANSI color escape string manipulations. Also contains
generic string containers.'''

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
_WORD_RE = re.compile("[^\\s-]*[\\s-]")				#split words by this regex
_UP_TO_WORD_RE = re.compile('(.*[{0}])*[^{0}]+[{0}]*'.format(_SANE_TEXTBOX))	#sane textbox word-backspace
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
_NUM_PREDEFINED = 5
#clear formatting
CLEAR_FORMATTING = '\x1b[m'
SELECTED = lambda x: _EFFECTS['reverse'][0] + x + CLEAR_FORMATTING
CHAR_CURSOR = '\x1b[s'
_INDENT_LEN = 4
_INDENT_STR = "    " 

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

class coloring:
	'''Simple container for a string and default color'''
	def __init__(self,string,default=None):
		self._str = string
		self.default = default
	def __repr__(self):
		'''Get the string contained'''
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
		'''Add effect to string (if test is true)'''
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

def preserve(line):
	'''Preserve formatting between lines (i.e in breaklines)'''
	ret = ''
	#only fetch after the last clear
	try: #return the last (assumed to be color) ANSI escape used
		ret += _LAST_COLOR_RE.findall(line)[-1]
		return ret + ''.join(_LAST_EFFECT_RE.findall(line))
	except IndexError: return ret

def breaklines(string,length):
	'''Break string (courteous of spaces) into a list of column-length length substrings'''
	string = string.expandtabs(_INDENT_LEN)
	THRESHOLD = length/2
	TABSPACE = length - _INDENT_LEN

	broken = []
	form = ''
	for i,line in enumerate(string.split("\n")):
		line += " " #ensurance that the last word will capture
		#tab the next lines
		space = (i and TABSPACE) or length
		newline = ((i and _INDENT_STR) or "") + form
		while line != "":
			match = _WORD_RE.match(line)
			word = match.group(0)
			wordlen = strlen(word)
			newspace = space - wordlen
			#just add the word
			if wordlen < space:
				space = newspace
				newline += word
				line = line[match.end(0):]
			#if there's room for some of the word, and we're not past a threshold
			elif space >= THRESHOLD:
				fitsize = columnslice(word, space)
				line = line[fitsize:]
				newline += word[:fitsize]
			if newspace <= 0:
				broken.append(newline+CLEAR_FORMATTING)
				newline = _INDENT_STR+preserve(newline)
				space = TABSPACE
		if newline != "":
			broken.append(newline+CLEAR_FORMATTING)
			form = preserve(newline)
	return broken,len(broken)

class scrollable:
	'''Scrollable text input'''
	def __init__(self,width,string = ""):
		self._str = string
		self._pos = 0
		self._disp = 0
		self._width = width
		self.password = False;
	def __repr__(self):
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
		text = text.replace("\n",r"\n").expandtabs(_INDENT_LEN)
		#TIME TO ITERATE
		escape,canbreak= 0,0
		#initial position, column num, position in string
		init,width,pos= 0,0,0
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
		return text[init:pos]
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
		ret = tabber.complete(search)
		if ret:
			self.append(ret + " ")
		
	#-----------------
	def _onchanged(self):
		'''Since this class is meant to take a 'good' slice of a string,'''+\
		''' It's useful to have this method when that slice is updated'''
		pass
	def setstr(self,new = None):
		if new is None: return
		self._str = new
		self.end()
	def setwidth(self,new = None):
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
	suggestionlists = []	#list of (references to) lists for each prefix paradigm
	def __init__(self,newPrefix,newList):
		'''Add a new tabbing method'''
		self.prefixes.append(newPrefix)
		self.suggestionlists.append(newList)
	
	def complete(incomplete):
		'''Find rest of a name in a list'''
		#O(|prefixes|*|suggestionlists|)
		for pno,prefix in enumerate(tabber.prefixes):
			preflen = len(prefix)
			if (incomplete[:preflen] == prefix):
				for complete in list(tabber.suggestionlists[pno]):
					if not complete.find(incomplete[preflen:]):	#in is bad practice
						return complete[len(incomplete)-1:]
				return ""
		return ""
