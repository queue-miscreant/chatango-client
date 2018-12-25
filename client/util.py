#!/usr/bin/env python3
#util.py
'''
Module for miscellaneous classes that are not inherently overlay or
display oriented. Contains classes like LazyIterList and PromoteSet
'''

import os
from os import path

#OTHER FUNCTIONS----------------------------------------------------------------
def tab_file(patharg):
	'''A file tabbing utility for ScrollSuggest'''
	findpart = patharg.rfind(path.sep)
	#offset how much we remove
	numadded = 0
	initpath, search = patharg[:findpart+1], patharg[findpart+1:]
	try:
		if not patharg or patharg[0] not in "~/": #try to generate full path
			newpath = path.join(os.getcwd(), initpath)
			ls = os.listdir(newpath)
		else:
			ls = os.listdir(path.expanduser(initpath))
	except (NotADirectoryError, FileNotFoundError):
		print("error occurred, aborting tab attempt on ", patharg)
		return [], 0

	suggestions = []
	if search: #we need to iterate over what we were given
		#insert \ for the suggestion parser
		suggestions = sorted([' ' in i and '"%s"' % (initpath+i).replace('"', r"\"")
			or (initpath+i).replace('"', r"\"") for i in ls if not i.find(search)])
	else: #otherwise ignore hidden files
		suggestions = sorted([' ' in i and '"%s"' % (initpath+i).replace('"', '\"')
			or (initpath+i).replace('"', r"\"") for i in ls if i.find('.')])

	if not suggestions:
		return [], 0
	return suggestions, numadded-len(patharg)

#LISTLIKE CLASSES---------------------------------------------------------------
class PromoteSet(list):
	'''Set with ordering like a list, whose elements can be promoted to the front'''
	def __init__(self, iterable=None):
		super().__init__()
		if iterable is not None:
			for i in iterable:
				self.append(i)
	def __repr__(self):
		return "PromoteSet({})".format(super().__repr__())

	def append(self, new):
		'''Add an item to the list'''
		if new in self:
			return
		super().append(new)
	def extend(self, iterable):
		'''Append each element in iterable'''
		super().extend(filter(lambda x: x not in self, iterable))
	def promote(self, index):
		'''Promote value in list to the front (index 0)'''
		if len(self) < 2:
			return
		i = 1
		found = False
		#look for the value
		while i <= len(self):
			if self[-i] == index:
				found = True
				break
			i += 1
		if not found:
			raise KeyError(index)
		if i == len(self):
			return
		#swap successive values
		while i < len(self):
			temp = self[-i-1]
			self[-i-1] = self[-i]
			self[-i] = temp
			i += 1

class LazyIterList(list):
	'''
	List-like class that builds itself on top of an iterator and has memory
	of current location. If `step` is called at the end of stored values and
	the iterator is not exhausted, it extends itself.
	'''
	def __init__(self, it):
		super().__init__()

		self._iter = it
		self._pos = 0
		try:
			self.append(next(it))
		except StopIteration:
			raise TypeError("Exhausted iterator used in LazyIterList init")

	def step(self, step):
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
						return None
				else:
					return None
			self._pos += 1
			return self[self._pos]
		#step backward
		if step == -1:
			#at the beginning already
			if not self._pos:
				return None
			self._pos -= 1
			return self[self._pos]
		return None

class History:
	'''
	Container class for historical entries, similar to an actual shell
	'''
	def __init__(self, *args, size=50):
		self.history = list(args)
		self._selhis = 0
		self._size = size
		#storage for next entry, so that you can scroll up, then down again
		self.bottom = None

	def __repr__(self):
		return "History(%s)" % repr(self.history)

	def nexthist(self, replace=""):
		'''Next historical entry (less recent)'''
		if not self.history:
			return ""
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

	def prevhist(self, replace=""):
		'''Previous historical entry (more recent)'''
		if not self.history:
			return ""
		if replace and self._selhis: #not at the bottom already
			self.history[-self._selhis] = replace
		#go forward in history
		self._selhis -= (self._selhis > 0)
		#return what we just retreived
		return (self._selhis and self.history[-self._selhis]) or self.bottom or ""

	def append(self, new):
		'''Add new entry in history and maintain maximum size'''
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
	def __init__(self, new_prefix=None, new_suggest=None):
		'''Add a new tabbing method'''
		if new_prefix is None and new_suggest is None:
			self.local_prefix = []
			self.local_suggest = []
			self.complete = lambda x: Tokenize.complete(x, self)
			return
		if new_prefix is None or new_suggest is None:
			raise TypeError("Invalid number of arguments for Tokenize. "+\
				"Must be 0 args for instance, or 2 args for global class")
		self.prefixes.append(new_prefix)
		self.suggestions.append(new_suggest)

	def add_complete(self, new_prefix, new_suggest):
		'''Add new completion token to the class'''
		self.local_prefix.append(new_prefix)
		self.local_suggest.append(new_suggest)

	@classmethod
	def complete(cls, incomplete, self=None):
		'''Find rest of a name in a list'''
		if isinstance(self, cls):
			#go through the local lists first
			ret = cls._complete(incomplete, self.local_prefix, self.local_suggest)
			if ret:	#don't cut off all completions
				return ret
		return cls._complete(incomplete, cls.prefixes, cls.suggestions)

	@staticmethod
	def _complete(incomplete, prefixes, suggestions):
		'''Backend for complete'''
		#O(|prefixes|*|suggestionlists|), so n**2
		for pno, prefix in enumerate(prefixes):
			preflen = len(prefix)
			if incomplete[:preflen] == prefix:
				search = incomplete[preflen:]
				return Tokenize.collapse_suggest(search, suggestions[pno])[0]
		return []

	@staticmethod
	def collapse_suggest(search, suggestion, add_space=True):
		'''
		When a list of suggestions (or a callable that generates them) has
		been found, cut the list down based on the length of the search
		'''
		truecut = 0			#how far to go back
		cut = len(search)	#the current depth into the suggestion
		if callable(suggestion):
			suggest, cut = suggestion(search)
			#if we want to back up the cursor instead of go into the suggestion
			if cut < 0:
				truecut = cut
				cut = 0
		else:
			suggest = [i for i in list(suggestion) if not i.find(search)]

		if add_space:
			add_space = ' '
		else:
			add_space = ''

		return [i[cut:]+add_space for i in suggest], truecut
