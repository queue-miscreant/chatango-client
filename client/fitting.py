#!/usr/bin/env python3
'''Methods/classes for fitting strings to column widths'''

import re
from .wcwidth import wcwidth
from .coloring import CLEAR_FORMATTING,preserve

CHAR_CURSOR = '\x1b[s'
_INDENT_LEN = 4
_INDENT_STR = "    "
#useful regexes
_WORD_RE = re.compile("[^ ]* ")
_UP_TO_WORD_RE = re.compile('(.* )[^ ]+ *')

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

def fitwordtolength(string,length):
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
				fitsize = fitwordtolength(word, space)
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
	def __init__(self,width):
		self._str = ""
		self._pos = 0
		self._disp = 0
		self.width = width
		self.history = []
		self._selhis = 0
	def __repr__(self):
		'''Return the raw text contained'''
		return self._str
	def display(self):
		'''Display text contained with cursor'''
		text = self._str[:self._pos] + CHAR_CURSOR + self._str[self._pos:]
		text = text.replace("\n",r"\n").replace("\t",r"\t").replace("\r",r"\r")
		text = text[self._disp:self._disp+self.width+len(CHAR_CURSOR)]
		return text[-fitwordtolength(text,self.width):]
	def movepos(self,dist):
		'''Move cursor by distance (can be negative). Adjusts display position'''
		if not len(self._str):
			self._pos,self._disp = 0,0
			return
		self._pos = max(0,min(len(self._str),self._pos+dist))
		curspos = self._pos - self._disp
		if curspos <= 0: #left hand side
			self._disp = max(0,self._disp+dist)
		elif (curspos+1) >= self.width: #right hand side
			self._disp = min(self._pos-self.width+1,self._disp+dist)
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
	def delword(self):
		'''Delete word behind cursor, like in sane text boxes'''
		pos = _UP_TO_WORD_RE.match(' '+self._str[:self._pos])
		if pos:
			#we started with a space
			span = pos.span(1)[1] - 1
			#how far we went
			self._str = self._str[:span] + self._str[self._pos:]
			self.movepos(span-self._pos)
		else:
			self._str = self._str[self._pos:]
			self._disp = 0
			self._pos = 0
	def clear(self):
		'''Clear cursor and string'''
		self._str = ""
		self._pos = 0
		self._disp = 0
	def home(self):
		'''Return to the beginning'''
		self._pos = 0
		self._disp = 0
	def end(self):
		'''Move to the end'''
		self._pos = 0
		self._disp = 0
		self.movepos(len(self._str))
	def nexthist(self):
		'''Next in history (less recent)'''
		if self.history:
			self._selhis += (self._selhis < (len(self.history)))
			self._str = self.history[-self._selhis]
			self.end()
	def prevhist(self):
		'''Back in history (more recent)'''
		if self.history:
			self._selhis -= (self._selhis > 0)
			#the next element or an empty string
			self._str = self._selhis and self.history[-self._selhis] or ""
			self.end()
	def appendhist(self,new):
		'''Add new entry in history'''
		self.history.append(new)
		self.history = self.history[-50:]
		self._selhis = 0
