#!/usr/bin/env python3
#TODO make coloring a little more user-friendly
'''String manipulations based on ANSI color sequences'''

import re
__all__ = ['SELECT_AND_MOVE','CLEAR_FORMATTING','coloring',
		'ANSI_ESC_RE','SELECTED','getColor']

#important regexes
_LAST_COLOR_RE = re.compile("\x1b"+r"\[[^m]*3[^m]*[^m]*m")
ANSI_ESC_RE = re.compile("\x1b"+r"\[[^A-z]*[A-z]")
#color constants-----------------------------------------------------------
#valid color namess to add
_COLORS =	['black'
		,'red'
		,'green'
		,'yellow'
		,'blue'
		,'magenta'
		,'cyan'
		,'white'
		,''
		,'none']
#0 = reverse; 1 = underline
_EFFECTS = ['\x1b[7m','\x1b[4m']
#storage for defined pairs
_COLOR_PAIRS = 	['\x1b[39;49m'	#Normal/Normal
		,'\x1b[31;47m'	#Red/White
		,'\x1b[31;41m'	#Red/Red
		,'\x1b[32;42m'	#Green/Green
		,'\x1b[34;44m']	#Blue/Blue
_NUM_PREDEFINED = len(_COLOR_PAIRS)
#clear formatting
CLEAR_FORMATTING = '\x1b[m'
SELECT_AND_MOVE = '\x1b[7m\x1b[s'
SELECTED = lambda x: _EFFECTS[0] + x + CLEAR_FORMATTING

class ColoringException(Exception):
	'''Exception for client.coloring'''
	pass

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
	def insertColor(self,p,c=None,add=True):
		'''Add a color at position p with color c'''
		c = self.default if c is None else c
		if isinstance(c,int):
			c = getColor(c,add)
		self._str =  self._str[:p] + c + self._str[p:]
		#return amount added to string
		return len(c)
	def addEffect(self, number, test = True):
		'''Add effect to string (if test is true)'''
		self._str = (test and _EFFECTS[number] or "") + self._str
	def findColor(self,end):
		'''Most recent color before end'''
		lastcolor = {end-i.end(0):i.group(0) for i in \
			 _LAST_COLOR_RE.finditer(self._str) if (end-i.end(0))>=0}
		try:
			return lastcolor[min(lastcolor)]
		except:
			return ''

def getColor(c,add=True):
	'''insertColor without position or coloring object'''
	try:
		return _COLOR_PAIRS[c + (add and _NUM_PREDEFINED)]
	except IndexError:
		raise ColoringException("Foreground/Background pair not defined")

def preserve(line):
	'''Preserve formatting between lines (i.e in breaklines)'''
	ret = ''
	#only fetch after the last clear
	for i in _EFFECTS:
		if i in line:
			ret += i
	try: #return the last (assumed to be color) ANSI escape used
		return ret + _LAST_COLOR_RE.findall(line)[-1]
	except IndexError: return ret

#Variables not exported by `from coloring import *`
#But imported by `import client`
def definepair(fore, bold = None, back = 'none'):
	'''Define a new foreground/background pair, with optional intense color'''
	global _COLOR_PAIRS
	pair = '\x1b[3%d' % _COLORS.index(fore);
	pair += bold and ";1" or ";22"
	pair += ';4%d' % _COLORS.index(back) or ""
	_COLOR_PAIRS.append(pair+'m')

def decolor(string):
	'''Replace all ANSI escapes with null string'''
	new = ANSI_ESC_RE.subn('',string)
	return new[0]
