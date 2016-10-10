#TODO oh god this is awful
#I need to be easily able to cascade a range of effects into colors

#maybe range of effects was misguided
#I could try to iterate over the list of formats and take out redundant fields (like an effect off before the intended position or an effect on after)
#That way, formats don't need O(n**2) at conversion time
#and if I put breaklines into coloring, I can just look at the parts of the formatting

#color/effect formatting should be binary data of the form
#(color bits)/(effect existence)/(effect is on or off)

#to make sure that no effects are added when coloring objects exist, create a mutex variable
#that disables adding a new effect after a coloring object has been instantiated

_COLOR_NAMES =	('black'
				,'red'
				,'green'
				,'yellow'
				,'blue'
				,'magenta'
				,'cyan'
				,'white'
				,''
				,'none')
#names of effects, and a tuple containing 'on' and 'off'
_EFFECTS =	{'reverse':		('\x1b[7m','\x1b[27m')
			,'underline':	('\x1b[4m','\x1b[24m')
			}
_EFFECTS_N =[('\x1b[7m','\x1b[27m'),
			('\x1b[4m','\x1b[24m')
			]
_NUM_EFFECTS = 2
#storage for defined pairs
_COLORS =	['\x1b[39;49m'	#Normal/Normal
			,'\x1b[31;47m'	#Red/White
			,'\x1b[31;41m'	#red
			,'\x1b[32;42m'	#green
			,'\x1b[34;44m'	#blue
			]

class newcoloring:
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
		colorstart = ((1 << (_NUM_EFFECTS << 1)) - 1)
		for pos,form in zip(self.positions,self.formatting):
			color = form >> (_NUM_EFFECTS << 1)
			effect = form & colorstart
			form = color > 0 and _COLORS[color-1] or ''
			if effect:
				for i in range(_NUM_EFFECTS):
					if effect & (1 << i):
						if effect & ((1 << _NUM_EFFECTS) << i):
							form += _EFFECTS_N[i][1]
						else:
							form += _EFFECTS_N[i][0]
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
		'''Insert positions/formatting into color dictionary. Formatting must '''+\
		'''be the proper color (in _COLORS, added with defColor)'''
		if position < 0: position += len(self._str)
		formatting = self.default if formatting is None else formatting
		#if type(formatting) is int: formatting = getColor_NEW(formatting)
		formatting += 1;
		formatting <<= _NUM_EFFECTS << 1;
		if position > self.maxpos:
			self.positions.append(position)
			self.formatting.append(formatting)
			self.maxpos = position
			return
		i = 0
		while position > self.positions[i]:
			i += 1
		if self.positions[i] == position:		#position already used
			effect = self.formatting[i] & ((1 << (_NUM_EFFECTS << 1)) - 1)
			self.formatting[i] = formatting | effect
		else:
			self.positions.insert(i,position)
			self.formatting.insert(i,formatting)

	def effectRange(self,start,end,formatting):
		'''Insert an effect at _str[start:end]. Formatting must be a number'''+\
		''' corresponding to an effect. As default, 0 is reverse and 1 is underline'''
		effectOn = 1 << formatting
		effectOff = effectOn << _NUM_EFFECTS
		i = 0
		if start > self.maxpos:
			self.positions.append(start)
			self.formatting.append(effectOn)
			self.maxpos = start
		else:
			while start > self.positions[i]:
				i += 1
			if self.positions[i] == start:	#if we're writing into a number
				self.formatting[i] |= effectOn
			else:
				self.positions.insert(i,start)
				self.formatting.insert(i,effectOn)
				i += 1

		while i < len(self.positions) and end > self.positions[i]:
			if self.formatting[i] & effectOff: #if this effect turns off here
				self.formatting[i] ^= effectOn | effectOff
				if not self.formatting[i]:
					self.formatting.pop(i)
					i -= 1
			i += 1
		if end > self.maxpos:
			self.positions.append(end)
			self.formatting.append(effectOn | effectOff)
			self.maxpos = end
		elif  self.positions[i] == end:		#position exists
			self.formatting[i] |= effectOn | effectOff
		else:
			self.positions.insert(i,end)
			self.formatting.insert(i,effectOn | effectOff)

	def addGlobalEffect(self, effectNumber):
		'''Add effect to string'''
		self.effectRange(0,len(self._str),effectNumber)

	def findColor(self,end):
		'''Most recent color before end. Safe when no matches are found'''
		if self.maxpos == -1:
			return self.default or 0
		if end > self.maxpos:
			return self.formatting[-1] >> (_NUM_EFFECTS << 1)
		last = -1
		for pos,form in zip(self.positions,self.formatting):
			if end < pos:
				return last >> (_NUM_EFFECTS << 1)
			last = form
		return last >> (_NUM_EFFECTS << 1)
	def colorByRegex(self, regex, groupFunction, group = 0, getLast = True):
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
			if getLast:
				#find the most recent color
				last = self.findColor(begin)
				self.insertColor(begin,groupFunction(find.group(group)))
				self.insertColor(end,last)
			else:
				self.insertColor(begin,groupFunction(find.group(group)))
	def effectByRegex(self, regex, effect, group = 0):
		for find in regex.finditer(self._str+' '):
			self.effectRange(effect,find.start(group),find.end(group))

