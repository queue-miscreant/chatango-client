#!/usr/bin/env python3
#util.py
'''
Module for miscellaneous classes that are not inherently overlay or 
display oriented. Contains classes like LazyIterList and PromoteSet
'''

import sys
from functools import partial

#HIGHER-ORDER FUNCTIONS---------------------------------------------------------
def staticize(func,*args,doc=None,**kwargs):
	'''functools.partial, but conserves or adds documentation'''
	ret = partial(func,*args,**kwargs)
	ret.__doc__ = doc or func.__doc__ or "(no documentation)"
	return ret

class override:
	'''
	Create a new function that returns `ret`. Avoids (or ensures) 
	firing _post in overlays
	'''
	def __init__(self,func,ret=0,nodoc=False):
		self.func = func
		self.ret = ret
		
		if not nodoc:
			docText = func.__doc__
			if docText is not None:
				if ret == 0:
					docText += " (keeps overlay open)"
				elif ret == -1:
					docText += " (and close overlay)"
			self.__doc__ = docText	#preserve documentation text

	def __call__(self,*args):
		self.func(*args)
		return self.ret

#LISTLIKE CLASSES---------------------------------------------------------------
class PromoteSet:
	'''Set with ordering like a list, whose elements can be promoted to the front'''
	def __init__(self,iterable = None):
		self._list = list()
		if iterable is not None:
			for i in iterable:
				self.append(i)
	def __repr__(self):
		return "PromoteSet({})".format(repr(self._list))
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

class LazyIterList(list):
	'''
	Listlike class that builds itself on top of an iterator. If attempted to
	step near the end and the iterator is not exhausted, it extends itself.
	'''
	def __init__(self,it):
		self._iter = it
		self._pos = 0
		try:
			self.append(next(it))
		except StopIteration:
			raise TypeError("Exhausted iterator used in LazyIterList init")

	def step(self,step):
		'''
		Select something in the direction step (1 or -1)
		Returns the item in the direction of the step, or if unable, None
		'''
		if step == 1:
			#step forward
			if self._pos + 1 >= len(self):
				if self._iter:	#if the iterator is active
					try:
						self.append(next(self._iter))
					except StopIteration:
						#just in case the following doesn't activate the gc
						del self._iter
						self._iter = None
						return
				else:
					return
			self._pos += 1
			return self[self._pos]
		elif step == -1:
			#step backward
			if not self._pos: return	#at the beginning already
			self._pos -= 1
			return self[self._pos]

class History:
	'''Container class for historical entries, similar to an actual shell'''
	def __init__(self, *args, size = 50):
		self.history = list(args)
		self._selhis = 0
		self._size = size
		#storage for next entry, so that you can scroll up, then down again
		self.bottom = None

	def __repr__(self):
		return "History(%s)" % repr(self.history)

	def nexthist(self,replace=""):
		'''Next historical entry (less recent)'''
		if not self.history: return ""
		if replace:
			if not self._selhis:
				#at the bottom, starting history
				self.bottom = replace
			else:
				#else, update the entry
				self.history[-self._selhis] = replace
		#go backward in history
		self._selhis += (self._selhis < (len(self.history)))
		#return what we just retrieved
		return self.history[-self._selhis]

	def prevhist(self,replace=""):
		'''Previous historical entry (more recent)'''
		if not self.history: return ""
		if replace and self._selhis: #not at the bottom already
			self.history[-self._selhis] = replace
		#go forward in history
		self._selhis -= (self._selhis > 0)
		#return what we just retreived
		return (self._selhis and self.history[-self._selhis]) or self.bottom or ""

	def append(self,new):
		'''Add new entry in history and maintain a size of at most 50'''
		if not self.bottom:
			#not already added from history manipulation
			self.history.append(new)
		self.bottom = None
		self.history = self.history[-self._size:]
		self._selhis = 0

#COMMANDLINE-LIKE FEATURES------------------------------------------------------
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
		truecut = 0			#how far to go back
		cut = len(search)	#the current depth into the suggestion
		if callable(suggestion):
			suggest,cut = suggestion(search)
			#if we want to back up the cursor instead of go into the suggestion
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

def escapeText(string):
	'''
	Formats a string with terminal like arguments
	(separated by unescaped spaces) into a tuple
	'''
	text = ""
	args = []
	escaping = False
	singleFlag = False
	doubleFlag = False
	for i in str(string):
		if escaping:
			escaping = False
			if not (singleFlag or doubleFlag):
				text += i
				continue
			text += '\\'
			
		if i == '\\':
			escaping = True
		elif i == "'":
			singleFlag ^= True
		elif i == '"':
			doubleFlag ^= True
		elif i == ' ' and not (singleFlag or doubleFlag):
			args.append(text)
			text = ""
		else:
			text += i
	if escaping:
		text += "\\"
	args.append(text)
	return args
