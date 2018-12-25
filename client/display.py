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
from .util import Tokenize

#all imports needed by overlay.py
__all__ =	["CLEAR_FORMATTING", "CHAR_CURSOR", "SELECT", "_COLORS"
			, "SELECT_AND_MOVE", "def_256_colors", "get_color"
			, "raw_num", "num_defined_colors", "collen", "numdrawing"
			, "columnslice", "Coloring", "Scrollable", "ScrollSuggest"]

BAD_CHARSETS = [
	  (119964, 26, ord('A'))	#uppercase math
	, (119990, 26, ord('a'))	#lowercase math
	, (119860, 26, ord('A'))	#uppercase italic math
	, (119886, 26, ord('a'))	#lowercase italic math
	, (120172, 26, ord('A'))	#uppercase fractur
	, (120198, 26, ord('a'))	#lowercase fractur
	, (120068, 26, ord('A'))	#uppercase math fractur
	, (120094, 26, ord('a'))	#lowercase math fractur
]

def parse_fractur(raw):
	cooked = ""
	for i in raw:
		#look for fractur and double-width fonts that don't comply with wcwidth
		for begin, length, onto in BAD_CHARSETS:
			if ord(i) in range(begin, begin+length):
				i = chr(ord(i) - begin + onto)
				break
		if ord(i) == 136:
			continue
		cooked += i
	return cooked

#REGEXES------------------------------------------------------------------------
#sane textbox splitting characters
_SANE_TEXTBOX =	r"\s\-\+/`~,;="
#sane textbox word-backspace
_UP_TO_WORD_RE = re.compile("([^{0}]*[{0}])*[^{0}]+[{0}]*".format(
	_SANE_TEXTBOX))
#sane textbox word-delete
_NEXT_WORD_RE =	re.compile("([{0}]*[^{0}]+)".format(_SANE_TEXTBOX))
#line breaking characters
_LINE_BREAKING = "- 　"

#COLORING CONSTANTS------------------------------------------------------------
#valid color names to add
_COLOR_NAMES = [
	  "black"
	, "red"
	, "green"
	, "yellow"
	, "blue"
	, "magenta"
	, "cyan"
	, "white"
	, ""
	, "none"
]

#storage for defined pairs
_COLORS = [
	  "\x1b[39;22;49m"	#Normal/Normal			0
	, "\x1b[31;22;47m"	#Red/White				1
	, "\x1b[31;22;41m"	#red	(ColorSliders)	2
	, "\x1b[32;22;42m"	#green	(ColorSliders)	3
	, "\x1b[34;22;44m"	#blue	(ColorSliders)	4
	, "\x1b[31;22;49m"	#red	(InputMux)		5
	, "\x1b[32;22;49m"	#green	(InputMux)		6
	, "\x1b[33;22;49m"	#yellow	(InputMux)		7
]
_NUM_PREDEFINED = len(_COLORS)

#a tuple containing 'on' and 'off'
_EFFECTS =	[
	  ("\x1b[7m", "\x1b[27m")
	, ("\x1b[4m", "\x1b[24m")
]
_EFFECTS_BITS = (1 << len(_EFFECTS))-1
_CAN_DEFINE_EFFECTS = True

CHAR_CURSOR = "\x1b[s"
SELECT = _EFFECTS[0][0]
SELECT_AND_MOVE = CHAR_CURSOR + SELECT
CLEAR_FORMATTING = "\x1b[m"
_TABLEN = 4

#arbitrary number of characters a scrollable can have and not scroll
MAX_NONSCROLL_WIDTH = 5

#COLORING STUFF-----------------------------------------------------------------
class DisplayException(Exception):
	'''Exception for handling errors from Coloring or Scrollable manipulation'''
	pass

def def_color(fore, back="none", intense=False):
	'''Define a new foreground/background pair, with optional intense color'''
	global _COLORS
	pair = "\x1b[3"
	if isinstance(fore, int):
		pair += "8;5;%d" % fore
	else:
		pair += str(_COLOR_NAMES.index(fore))
		pair += intense and ";1" or ";22"
	if isinstance(back, int):
		pair += ";48;5;%d" % back
	else:
		pair += ";4%d" % _COLOR_NAMES.index(back)
	_COLORS.append(pair+"m")

def def_effect(on, off):
	'''Define a new effect, turned on with `on`, and off with `off`'''
	if not _CAN_DEFINE_EFFECTS:
		raise DisplayException("cannot define effect; a Coloring object already exists")
	global _EFFECTS, _EFFECTS_BITS
	_EFFECTS.append((on, off))
	_EFFECTS_BITS = (_EFFECTS_BITS << 1) | 1

def def_256_colors():
	for i in range(256):
		def_color(i)

def get_color(color):
	'''insertColor without position or coloring object'''
	try:
		return _COLORS[color + _NUM_PREDEFINED]
	except IndexError:
		raise DisplayException("Color definition %d not found" % color)

def raw_num(c):
	'''
	Get raw pair number, without respect to number of predefined ones.
	Use in conjunction with getColor or Coloring.insertColor to use
	predefined colors
	'''
	if c < 0:
		raise DisplayException("raw numbers must not be below 0")
	return c - _NUM_PREDEFINED

def num_defined_colors():
	'''
	Get the beginning index in _COLORS (adjusted for _NUM_PREDEFINED) before
	more colors are defined. Used in toggle256.
	'''
	return len(_COLORS) - _NUM_PREDEFINED


class Coloring:
	'''Container for a string and coloring to be done'''
	def __init__(self, string, remove_fractur=True):
		global _CAN_DEFINE_EFFECTS
		_CAN_DEFINE_EFFECTS = False
		if remove_fractur:
			string = parse_fractur(string)
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
		return "<Coloring string = {}, positions = {}, formatting = {}>".format(
			repr(self._str), self._positions, self._formatting)

	def __str__(self):
		'''Get the string contained'''
		return self._str

	def __format__(self, *args):
		'''Colorize the string'''
		ret = ""
		tracker = 0
		last_effect = 0
		for pos, form in zip(self._positions, self._formatting):
			color = form >> len(_EFFECTS)
			next_effect = form & _EFFECTS_BITS
			formatting = _COLORS[color-1] if color > 0 else ""
			for i, effect in enumerate(_EFFECTS):
				if (1 << i) & next_effect:
					if (1 << i) & last_effect:
						formatting += effect[1]
					else:
						formatting += effect[0]
			ret += self._str[tracker:pos] + formatting
			tracker = pos
			last_effect = next_effect
		ret += self._str[tracker:]
		return ret + CLEAR_FORMATTING

	def sub_slice(self, sub, start, end=None):
		'''
		Overwrite rest of string at position `start`; optionally end overwrite
		at position `end`. Basically works as slice assignment.
		'''
		if start < 0:
			start = max(0, start+len(self._str))
		pos = 0
		for pos, i in enumerate(self._positions):
			if i >= start:
				break
		self._positions = self._positions[:pos]
		self._formatting = self._positions[:pos]

		if end:
			if end < 0:
				end	= max(0, len(self._str))
			for pos, i in enumerate(self._positions):
				if i > start:
					self._positions[pos] = i + len(sub)
			last = self.find_color(start) or raw_num(0)
			self._insert_color(end, last)
			self._str = self._str[:start] + sub + self._str[end:]
			return
		self._str = self._str[:start] + sub

	def add_indicator(self, sub, color=None):
		'''
		Replace some spaces at the end of a string. Optionally inserts a color
		for the string `sub`. Useful for ListOverlays.
		'''
		if sub == "":
			return
		pos, columns = 1, collen(sub)
		while pos <= columns:
			# keep a space, so pos-1
			if self._str[-pos-1] != ' ':
				# fewer columns in `sub` than room in _str
				if columns < pos-1:
					raise DisplayException("Not enough room for indicator %s" %\
						sub)
				sub = sub[:columnslice(sub, pos-2)] + "…"
				break
			pos += 1
		pos -= 1
		self._str = self._str[:-pos] + sub
		if color:
			self.insert_color(-pos, color)

	def colored_at(self, position):
		'''return a bool that represents if that position is colored yet'''
		return position in self._positions

	def _insert_color(self, position, formatting):
		'''insert_color backend that doesn't do sanity checking on formatting'''
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
			self._positions.insert(i, position)
			self._formatting.insert(i, formatting)

	def insert_color(self, position, formatting):
		'''
		Insert positions/formatting into color dictionary
		formatting must be a proper color (in _COLORS, added with def_color)
		'''
		if position < 0:
			position = max(position+len(self._str), 0)
		formatting += _NUM_PREDEFINED + 1
		formatting <<= len(_EFFECTS)
		self._insert_color(position, formatting)

	def effect_range(self, start, end, formatting):
		'''
		Insert an effect at _str[start:end]
		formatting must be a number corresponding to an effect
		'''
		if start < 0:
			start = len(self._str) + start
		if end < 0:
			end = len(self._str) + end
		if start > end and not end:
			end = len(self._str) #shortcut
		if start >= end:
			return

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
			self._positions.insert(i, start)
			self._formatting.insert(i, effect)
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
			self._positions.insert(i, end)
			self._formatting.insert(i, effect)

	def add_global_effect(self, effect_number, pos=0):
		'''Add effect to string'''
		self.effect_range(pos, len(self._str), effect_number)

	def find_color(self, end):
		'''Most recent color before end. Safe when no matches are found'''
		if self._maxpos == -1:
			return None
		if end > self._maxpos:
			return self._formatting[-1]
		last = self._formatting[0]
		for pos, form in zip(self._positions, self._formatting):
			if end < pos:
				return last
			last = form
		return last

	def color_by_regex(self, regex, group_func, fallback=None, group=0):
		'''
		Color from a compiled regex, generating the respective color number
		from captured group. group_func should be an int or callable that
		returns int
		'''
		if not callable(group_func):
			ret = group_func	#get another header
			group_func = lambda x: ret
		# only get_last when supplied a color number fallback
		get_last = False
		if isinstance(fallback, int):
			get_last = True

		for find in regex.finditer(self._str):
			begin = find.start(group)
			end = find.end(group)
			# insert the color
			if get_last:
				# find the most recent color
				last = self.find_color(begin)
				last = fallback if last is None else last
				self.insert_color(begin, group_func(find.group(group)))
				# backend because last is already valid
				self._insert_color(end, last)
			else:
				self.insert_color(begin, group_func(find.group(group)))

	def effect_by_regex(self, regex, effect, group=0):
		for find in regex.finditer(self._str+' '):
			self.effect_range(find.start(group), find.end(group), effect)

	def breaklines(self, length, outdent="", keep_empty=True):
		'''
		Break string (courteous of spaces) into a list of strings spanning
		up to `length` columns
		'''
		outdent_len = collen(outdent)
		TABSPACE = length - outdent_len	#the number of columns sans the outdent
		THRESHOLD = length >> 1	#number of columns before we break on a nice
								#character rather than slicing a word in half
		broken = []		#array of broken lines with formatting

		start = 0			#start at 0
		space = length		#number of columns left
		line_buffer = ""	#broken line with formatting; emptied into `broken`

		format_pos = 0	#self.formatting iterator
		get_format = bool(len(self._positions))	#is there a next color?
		last_color = 0	#last color used; used to continue it after line breaks
		last_effect = 0	#last effect used; //
		lastcol = 0		#last possible breaking character position
		for pos, j in enumerate(self._str):	#character by character, the old fashioned way
			lenj = wcwidth(j)
			#if we have a 'next color', and we're at that position
			if get_format and pos == self._positions[format_pos]:
				line_buffer += self._str[start:pos]
				start = pos
				#decode the color/effect
				last_color = (self._formatting[format_pos] >> len(_EFFECTS)) \
					or last_color
				next_effect = self._formatting[format_pos] & _EFFECTS_BITS
				format_pos += 1
				get_format = format_pos != len(self._positions)
				#do we even need to draw this?
				if space > 0:
					line_buffer += _COLORS[last_color-1] \
						if last_color > 0 else ""
					for i, effect in enumerate(_EFFECTS):
						if (1 << i) & next_effect:
							if (1 << i) & last_effect:
								line_buffer += effect[1]
							else:
								line_buffer += effect[0]
				#effects are turned off and on by the same bit
				last_effect ^= next_effect
			if j == '\t':
				#tabs are the length of outdents
				lenj = outdent_len
				line_buffer += self._str[start:pos]
				start = pos+1 #skip over tab
				line_buffer += ' '*min(lenj, space)
			elif j == '\n':
				#add the new line
				line_buffer += self._str[start:pos]
				if (line_buffer.rstrip() != outdent.rstrip()) or keep_empty:
					broken.append(line_buffer + CLEAR_FORMATTING)
				#refresh variables
				line_buffer = outdent
				line_buffer += _COLORS[last_color-1] if last_color > 0 else ""
				for i, effect in enumerate(_EFFECTS):
					if last_effect & (1 << i):
						line_buffer += effect[0]
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
				line_buffer += self._str[start:pos+1]
				start = pos+1
				lastcol = space
			if space <= 0:			#time to break
				#do we have a 'last space (breaking char)' recent enough to split after?
				if 0 < lastcol < THRESHOLD:
					broken.append(line_buffer + CLEAR_FORMATTING)
					line_buffer = outdent
					line_buffer += _COLORS[last_color-1] \
						if last_color > 0 else ""
					for i, effect in enumerate(_EFFECTS):
						if (1 << i) & last_effect:
							line_buffer += effect[0]
					lenj += lastcol
				#split on a long word
				else:
					broken.append(line_buffer + self._str[start:pos] + \
						CLEAR_FORMATTING)
					line_buffer = outdent
					line_buffer += _COLORS[last_color-1] \
						if last_color > 0 else ""

					for i, effect in enumerate(_EFFECTS):
						if (1 << i) & last_effect:
							line_buffer += effect[0]
					start = pos
				lastcol = 0
				space = TABSPACE - lenj

		#empty the buffer one last time
		line_buffer += self._str[start:]
		if line_buffer.rstrip() != outdent.rstrip():
			broken.append(line_buffer+CLEAR_FORMATTING)

		#guarantee that a broken empty string is a singleton of an empty string
		if not broken:
			broken = [""]

		return broken

def collen(string):
	'''Column width of a string'''
	escape = False
	ret = 0
	for i in string:
		temp = (i == '\x1b') or escape
		#not escaped and not transitioning to escape
		if not temp:
			char_width = wcwidth(i)
			ret += (char_width > 0) and char_width
		elif i.isalpha(): #is escaped and i is alpha
			escape = False
			continue
		escape = temp
	return ret

def numdrawing(string, width=-1):
	'''
	Number of drawing characters in the string (up to width).
	Ostensibly the number of non-escape sequence characters
	'''
	if not width:
		return 0
	escape = False
	ret = 0
	for i in string:
		temp = (i == '\x1b') or escape
		#not escaped and not transitioning to escape
		if not temp:
			ret += 1
			if ret == width:
				return ret
		elif i.isalpha(): #is escaped and i is alpha
			escape = False
			continue
		escape = temp
	return ret

def columnslice(string, width):
	'''Fit string to column width'''
	escape = False
	#number of columns passed, number of chars passed
	trace, lentr = 0, 0
	for lentr, i in enumerate(string):
		temp = (i == '\x1b') or escape
		#escapes (FSM-style)
		if not temp:
			char = wcwidth(i)
			trace += (char > 0) and char
			if trace > width:
				return lentr
		elif i.isalpha(): #is escaped and i is alpha
			escape = False
			continue
		escape = temp
	return lentr + 1

#SCROLLABLE CLASSES-------------------------------------------------------------
class Scrollable:
	'''Scrollable text input'''
	def __init__(self, width, string=""):
		if width <= _TABLEN:
			raise DisplayException("Cannot create Scrollable smaller "+\
				" or equal to tab width %d"%_TABLEN)
		self._str = string
		self._width = width
		#position of the cursor and display column of the cursor
		self._pos = len(string)
		self._disp = max(0, collen(string)-width)
		#nonscrolling characters
		self._nonscroll = ""
		self._nonscroll_width = 0
		self.password = False

	def __repr__(self):
		return "Scollable({},{})".format(self._width, repr(self._str))

	def __str__(self):
		'''Return the raw text contained'''
		return self._str

	def __format__(self, *args):
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
			elif char in ('\n', '\r'):
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
			elif char in ('\n', '\r'):
				width -= 2	#for \n
			elif ord(char) >= 32:
				width -= wcwidth(char)
			start += 1
		if self.password:
			if not endwidth: #cursor is at the end
				endwidth = self._width
			else:
				endwidth -= 1
			return self._nonscroll+('*'*endwidth)+CHAR_CURSOR+\
				('*'*(width-endwidth))
		text = self._nonscroll+self._str[start:self._pos]+\
			CHAR_CURSOR+self._str[self._pos:end]
		#actually replace the lengths I asserted earlier
		return text.replace('\n', '\\n').replace('\r',
			'\\r').replace('\t', ' '*_TABLEN)
	#SET METHODS----------------------------------------------------------------
	def _onchanged(self):
		'''Useful callback to retreive a new 'good' slice of a string'''
		pass

	def setstr(self, new):
		'''Set content of scrollable'''
		self._str = new
		self.end()

	def setnonscroll(self, new):
		'''Set nonscrolling characters of scrollable'''
		check = collen(new)
		if check > MAX_NONSCROLL_WIDTH:
			new = new[:columnslice(new, MAX_NONSCROLL_WIDTH)]
		self._nonscroll = new
		self._nonscroll_width = min(check, MAX_NONSCROLL_WIDTH)
		self._onchanged()

	def setwidth(self, new):
		'''Set width of the scrollable'''
		if new <= 0:
			raise DisplayException()
		self._width = new
		self._onchanged()

	#TEXTBOX METHODS-----------------------------------------------------------
	def movepos(self, dist):
		'''Move cursor by distance (can be negative). Adjusts display position'''
		if not self._str:
			self._pos, self._disp = 0, 0
			self._onchanged()
			return
		self._pos = max(0, min(len(self._str), self._pos+dist))
		curspos = self._pos - self._disp
		if curspos <= 0: #left hand side
			self._disp = max(0, self._disp+dist)
		elif (curspos+1) >= self._width: #right hand side
			self._disp = min(self._pos-self._width+1, self._disp+dist)
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
	def append(self, new):
		'''Append string at cursor'''
		self._str = self._str[:self._pos] + new + self._str[self._pos:]
		self.movepos(len(new))
	#CHARACTER DELETION METHODS-------------------------------------------------
	def backspace(self):
		'''Backspace one char at cursor'''
		#don't backspace at the beginning of the line
		if not self._pos:
			return
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

class ScrollSuggest(Scrollable):
	'''
	A Scrollable extension with suggestion built in
	If you need to extend a Scrollable, it's probably this one
	'''
	def __init__(self, width, string=""):
		super().__init__(width, string)
		self._argument_complete = {}
		#completer
		self.completer = Tokenize()
		self._suggest_list = []
		self._suggest_num = 0
		self._keep_suggest = False
		#storage vars
		self._lastdisp = None
		self._lastpos = None

	def _onchanged(self):
		'''Get rid of stored suggestions'''
		if not self._keep_suggest:
			self._suggest_num = -1
			self._suggest_list.clear()
			self._lastpos, self._lastdisp = None, None
		self._keep_suggest = False

	def add_command(self, command, suggestion):
		self._argument_complete[command] = suggestion

	def complete(self):
		'''Complete the last word before the cursor or go to next suggestion'''
		#need to generate list
		if not self._suggest_list:
			close_quote = False
			if self._str[:self._pos].count('"') % 2:
				lexicon = shlex(self._str[:self._pos]+'"', posix=True)
				close_quote = True
			else:
				lexicon = shlex(self._str[:self._pos], posix=True)
			lexicon.quotes = '"' #no single quotes
			lexicon.wordchars += ''.join(self.completer.local_prefix) + \
				''.join(self.completer.prefixes) + '/~' #add in predefined characters
			argsplit = []
			last_token = lexicon.get_token()
			while last_token:
				argsplit.append(last_token)
				last_token = lexicon.get_token()

			#last character was a space
			completed_word = self._str[self._pos-1:self._pos] == ' '

			if (completed_word or len(argsplit) > 1) and self._argument_complete:
				verb, suggest = argsplit[0], '' if completed_word else argsplit[-1]

				if verb in self._argument_complete:
					complete = self._argument_complete[verb]
					temp_suggest, temp = Tokenize.collapse_suggest(suggest,
						complete, add_space=False)

					#temp is the amount of characters to keep for the suggestion
					if temp_suggest:
						#-2 for both quotes being counted
						started_with_quote = self._str[-len(suggest)-1] == '"'
						if started_with_quote or close_quote:
							#if we're closing a quote, then we only need to account
							#for one quote
							temp -= 1 + (not close_quote)
							temp_suggest = [(i[-1] != '"') and ('"%s"' % i) or i
								for i in temp_suggest]

						self._str = self._str[:self._pos+temp] + self._str[self._pos:]
						self.movepos(temp)
						self._suggest_list = temp_suggest

			#just use a prefix
			if argsplit and not self._suggest_list:
				search = argsplit[-1]
				if completed_word:
					#no need to try to complete if the word has been completed by a space
					return False
				if len(argsplit) == 1:
					search = self._nonscroll + search
				self._suggest_list = self.completer.complete(search)

		#if there's a list or we could generate one
		if self._suggest_list:
			self._suggest_num = (self._suggest_num+1) % len(self._suggest_list)
			suggestion = self._suggest_list[self._suggest_num]
			#no need to tab through a single one
			if len(self._suggest_list) > 1:
				self._keep_suggest = True
				if self._lastpos is None:
					self._lastpos, self._lastdisp = self._pos, self._disp
				else:
					self._str = self._str[:self._lastpos] + self._str[self._pos:]
					self._pos, self._disp = self._lastpos, self._lastdisp
			self.append(suggestion)
			return True
		return False

	def backcomplete(self):
		'''Return to previous entry in tab list'''
		if self._suggest_list:
			self._suggest_num = (self._suggest_num-1)%len(self._suggest_list)
			suggestion = self._suggest_list[self._suggest_num]
			self._keep_suggest = True
			if self._lastpos is None:
				self._lastpos, self._lastdisp = self._pos, self._disp
			else:
				self._str = self._str[:self._lastpos] + self._str[self._pos:]
				self._pos, self._disp = self._lastpos, self._lastdisp
			self.append(suggestion)
			return True
		return False
