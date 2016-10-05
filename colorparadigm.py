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
#storage for defined pairs
_COLORS =	['\x1b[39;49m'	#Normal/Normal
			,'\x1b[31;47m'	#Red/White
			,'\x1b[31;41m'	#red
			,'\x1b[32;42m'	#green
			,'\x1b[34;44m'	#blue
			]
_NUM_PREDEFINED = len(_COLORS)

testrange = [[3,4],[5,6],[7,8],[9,11]]

class coloring:
	'''Container for a string and default color'''
	def __init__(self,string,default=None):
		self._str = string
		self.default = default
		self.colors = []
		self.positions = []
		self.maxpos = -1
		#effects need to span a range, so they need a dictionary
		self.effects = {}
	def __repr__(self):
		'''Get the string contained'''
		return "coloring({}, positions = {}, formats = {})".format(repr(self._str),self.positions,self.colors)
	def __str__(self):
		'''Colorize the string'''
		ret = self._str
		tracker = 0
		for effectname,rangelist in self.effects.items():
			for i in rangelist:
				self.insertColor(i[0],_EFFECTS[effectname][0])
				self.insertColor(i[1],_EFFECTS[effectname][1])
		for pos,form in zip(self.positions,self.colors):
			if type(form) == int:
				form = _COLORS[_NUM_PREDEFINED+form]
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
		lenother = len(other)
		for pos,i in enumerate(self.positions):
			self.positions[pos] = i + lenother
		for i in self.effects:
			for j in self.effects[i]:
				j[0] += lenother
				j[1] += lenother
		return self
	def insertColor(self,position,color=None):
		'''Insert positions/formatting into color dictionary'''
		if position is None: return
		color = self.default if color is None else color
		if position > self.maxpos:
			self.positions.append(position)
			self.colors.append(color)
			self.maxpos = position
			return
		i = 0
		while position > self.positions[i]:
			i += 1
		if self.positions[i] == position:		#position already used
			self.colors[i] = color
		else:
			self.positions.insert(i,position)
			self.colors.insert(i,color)
	def addEffectRange(self,effectName,begin,end):
		rangelist = []
		try:
			rangelist = self.effects[effectName]
		except KeyError:
			if effectName in _EFFECTS:
				self.effects[effectName] = rangelist
			else:
				raise DisplayException("effect {} not found".format(effectName))
		lenlist = len(rangelist)
		i = 0
		for i,r in enumerate(rangelist):
			if r[0] >= begin:
				break
			elif r[1] >= begin:
				begin = r[0] 
				break
		if i == lenlist:
			rangelist.append([begin,end])
			return
		j = 0	
		while i < lenlist-j:		#until the range
			if rangelist[i][1] >= end:
				rangelist[i][0] = begin
				rangelist[i][1] = max(end,rangelist[i][1])
				return
			rangelist.pop(i)
			j += 1
		rangelist.append([begin,end])

	def addGlobalEffect(self, effect):
		'''Add effect to string'''
		self.addEffectRange(effect,0,len(self._str))

	def findColor(self,end):
		'''Most recent color before end. Safe when no matches are found'''
		try:
			if end > self.positions[-1]:
				return self.colors[-1]
		except IndexError:
			return None
		last = ''
		for pos,form in zip(self.positions,self.colors):
			if end < pos:
				return last
			last = form

	def colorByRegex(self, regex, groupFunction, group = 0,_ = None):
		'''Color from a compiled regex, generating the respective color number from captured group. '''+\
		'''groupFunction should be an int (or string) or callable that returns int (or string)'''
		if not callable(groupFunction):
			ret = groupFunction	#get another header
			groupFunction = lambda x: ret
		for find in regex.finditer(self._str+' '):
			begin = find.start(group)
			end = find.end(group)
			#find the most recent color
			last = self.findColor(begin)
			self.insertColor(begin,groupFunction(find.group(group)))
			self.insertColor(end,last)

	def effectByRegex(self, regex, effect, group = 0):
		for find in regex.finditer(self._str+' '):
			self.addEffectRange(effect,find.start(group),find.end(group))

