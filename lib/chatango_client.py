#!/usr/bin/env python3
#chatango_client.py
'''
Chatango extensions to bridge client/ and ch.py
Specifically, the bound instances ChatangoOverlay and ChatBot
which reference each other through ChatangoOverlay.bot and
ChatBot.mainOverlay
'''
from . import ch
from . import client
import os
import re
import asyncio

__all__ = ["ChatBot","ChatangoOverlay","tabFile","convertTo256","getColor"]

#constants for chatango
FONT_FACES = \
	["Arial"
	,"Comic Sans"
	,"Georgia"
	,"Handwriting"
	,"Impact"
	,"Palatino"
	,"Papyrus"
	,"Times New Roman"
	,"Typewriter" ]
FONT_SIZES = [9,10,11,12,13,14]
OPTION_NAMES = \
	["Mouse:"
	,"Multiple link open warning threshold:"
	,"Save ignore list:"
	,"Console bell on reply:"
	,"256 colors:"
	,"HTML colors:"
	,"Colorize anon names:"]
ONLY_ONCE = True

def parsePost(post, me, ishistory):
	#and is short-circuited
	isreply = me is not None and ('@'+me.lower() in post.post.lower())
	#format as ' user: message'; the space is for the channel
	msg = " {}: {}".format(post.user,post.post)
	#links
	client.parseLinks(post.post, ishistory)
	#extra arguments. use in colorizers
	return (msg, post, isreply, ishistory)

class ChatBot(ch.Manager):
	'''Bot for interacting with the chat'''
	members = client.PromoteSet()
	#event hookup
	_events = \
		{"onMemberJoin": None
		,"onMemberLeave": None
		,"onFloodBan": None
		,"onFloodBanRepeat": None
		,"onFloodWarning": None}

	def __init__(self,creds,parent):
		super(ChatBot,self).__init__(creds["user"],creds["passwd"],loop=parent.loop)
		self.creds = creds
		self.channel = 0
		self.isinited = 0
		#default to the given user name
		self.me = creds.get("user") or None
		self.joinedGroup = None
		self.mainOverlay = ChatangoOverlay(parent,self)
		self.mainOverlay.add()
		self.visited_links = [] #TODO move into ChatangoOverlay instead
		#list references
		self.ignores = self.creds["ignores"]
		self.filtered_channels = self.creds["filtered_channels"]
		self.options = self.creds["options"]

		#new tabbing for members, ignoring the # and ! induced by anons and tempnames
		client.Tokenize('@',self.members)
		self.loop.create_task(self.onInit())

	def _runEvent(self,event,*args):
		try:
			self._events[event](self,*args)
		except TypeError: pass
	@classmethod
	def addEvent(cls,eventname,func):
		if eventname in cls._events:
			cls._events[eventname] = func
	
	@asyncio.coroutine
	def onInit(self):
		self.members.clear()
		yield from self.mainOverlay.msgSystem("Connecting")
		yield from self.joinGroup(self.creds["room"])
	
	def stop(self):
		if not self.isinited: return
		super(ChatBot,self).stop()
	
	def reconnect(self):
		if not self.isinited: return
		self.leaveGroup(self.joinedGroup)
		self.mainOverlay.clear()
		client.clearLinks()
		self.onInit()
	
	def changeGroup(self,newgroup):
		self.leaveGroup(self.joinedGroup)
		self.creds["room"] = newgroup
		client.clearLinks()
		self.joinGroup(newgroup)

	def setFormatting(self):
		group = self.joinedGroup
		
		group.fColor = self.creds["formatting"][0]
		group.nColor = self.creds["formatting"][1]
		group.fFace = self.creds["formatting"][2]
		group.fSize = self.creds["formatting"][3]
	
	def tryPost(self,text):
		if self.joinedGroup is None: return
		self.loop.create_task(self.joinedGroup.sendPost(text,self.channel))
	
	@asyncio.coroutine
	def onConnect(self, group):
		self.joinedGroup = group
		self.setFormatting()
		self.me = group.username
		if self.me[0] in "!#": self.me = self.me[1:]
		self.mainOverlay.parent.updateinfo(None,"{}@{}".format(self.me,group.name))
		#show last message time
		yield from self.mainOverlay.msgSystem("Connected to "+group.name)
		yield from self.mainOverlay.msgTime(group.last,"Last message at ")
		yield from self.mainOverlay.msgTime()
		
	#on message
	@asyncio.coroutine
	def onMessage(self, group, post):
		'''On message. No event because you can just use ExamineMessage'''
		#double check for anons
		user = post.user
		if user[0] in '#!': user = user[1:]
		if user not in self.members:
			self.members.append(user.lower())
		msg = parsePost(post, self.me, False)
		#						  isreply		ishistory
		if self.options["bell"] and msg[2] and not msg[3]:
			client.soundBell()

		self.members.promote(user.lower())
		yield from self.mainOverlay.msgPost(*msg)

	@asyncio.coroutine
	def onHistoryDone(self, group, history):
		'''On retrieved history'''
		for post in history:
			user = post.user
			if user[0] in '#!': user = user[1:]
			if user not in self.members:
				self.members.append(user.lower())
			msg = parsePost(post, self.me, True)
			yield from self.mainOverlay.msgPrepend(*msg)
		self.mainOverlay.canselect = True

	@asyncio.coroutine
	def onFloodWarning(self, group):
		self.mainOverlay.msgSystem("Flood ban warning issued")
		self._runEvent("onFloodWarning",group)

	@asyncio.coroutine
	def onFloodBan(self, group, secs):
		self.onFloodBanRepeat(group, secs)
		self._runEvent("onFloodBan",group,secs)

	@asyncio.coroutine
	def onFloodBanRepeat(self, group, secs):
		self.mainOverlay.msgSystem("You are banned for %d seconds"%secs)
		self._runEvent("onFloodRepeat",group,secs)
	
	@asyncio.coroutine
	def onParticipants(self, group):
		'''On received joined members. No event because this is run on successful connect'''
		self.members.extend(group.userlist)
		yield from self.mainOverlay.recolorlines()

	@asyncio.coroutine
	def onUsercount(self, group):
		'''On user count changed. No event because this is run on member join/leave'''
		self.mainOverlay.parent.updateinfo(str(group.usercount))

	@asyncio.coroutine
	def onMemberJoin(self, group, user):
		if user != "anon":
			self.members.append(user)
		#notifications
		self.mainOverlay.parent.newBlurb("%s has joined" % user)
		self._runEvent("onMemberJoin",group,user)

	@asyncio.coroutine
	def onMemberLeave(self, group, user):
		self.mainOverlay.parent.newBlurb("%s has left" % user)
		self._runEvent("onMemberLeave",group,user)

	@asyncio.coroutine
	def onConnectionError(self, group, error):
		if error == "lost":
			message = self.mainOverlay.msgSystem("Connection lost; press any key to reconnect")
			#XXX
			client.BlockingOverlay(self.mainOverlay.parent,
				client.daemonize(self.reconnect),"connect").add()
		else:
			self.mainOverlay.msgSystem("Connection error occurred. Try joining another room with ^T")

#OVERLAY EXTENSION--------------------------------------------------------------
class ChatangoOverlay(client.MainOverlay):
	def __init__(self,parent,bot):
		super(ChatangoOverlay, self).__init__(parent)
		self.bot = bot
		self.canselect = False
		self.addKeys({	"enter":	self.onenter
						,"a-enter":	self.onaltenter
						,"tab":		self.ontab
						,"f2":		self.linklist
						,"f3":		self.listmembers
						,"f4":		self.setformatting
						,"f5":		self.setchannel
						,"f12":		self.options
						,"^n":		self.addignore
						,"^t":		self.joingroup
						,"^g":		self.openlastlink
						,"^r":		self.reloadclient
				,"mouse-left":		self.clickOnLink
				,"mouse-middle":	client.override(client.staticize(self.openSelectedLinks),1)
		},1)	#these are methods, so they're defined on __init__

	def _maxselect(self):
		#when we've gotten too many messages
		group = self.bot.joinedGroup
		if group:
			self.canselect = False
			group.getMore()
			#wait until we're done getting more
			self.parent.newBlurb("Fetching more messages")
	
	def openSelectedLinks(self):
		message = self.getselected()
		try:	#don't bother if it's a system message (or one with no "post")
			msg = message[1][0].post
		except: return
		alllinks = client.LINK_RE.findall(msg)
		def openall():
			for i in alllinks:
				client.open_link(self.parent,i)
				if i not in self.bot.visited_links:
					self.bot.visited_links.append(i)
			#don't recolor if the list is empty
			#need to recolor ALL lines, not just this one
			if alllinks: self.parent.loop.create_task(self.recolorlines())
				
		if len(alllinks) >= self.bot.options["linkwarn"]:
			self.parent.holdBlurb(
				"Really open {} links? (y/n)".format(len(alllinks)))
			client.ConfirmOverlay(self.parent, openall).add()
		else:
			openall()

	def clickOnLink(self,x,y):
		msg = self.clickMessage(x,y)
		if not msg: return 1
		msg, pos = msg
		link = ""
		smallest = -1
		for i in client.LINK_RE.finditer(str(msg[0])):
			linkpos = (i.start() + i.end()) // 2
			distance = abs(linkpos - pos)
			if distance < smallest or smallest == -1:
				smallest = distance
				link = i.group()
		if link:
			client.open_link(self.parent,link)
			self.bot.visited_links.append(link)
			self.parent.loop.create_task(self.recolorlines())
		return 1

	def onenter(self):
		'''Open selected message's links or send message'''
		if self.isselecting():
			self.openSelectedLinks()
			return
		text = str(self.text)
		#if it's not just spaces
		if text.count(' ') != len(text):
			#add it to the history
			self.text.clear()
			self.history.append(text)
			#call the send
			self.bot.tryPost(text)
	
	def onaltenter(self):
		'''Open link and don't stop selecting'''
		if self.isselecting():
			self.openSelectedLinks()
		return 1

	def ontab(self):
		'''Reply to selected message or complete member name'''
		if self.isselecting():
			try:
				#allmessages contain the colored message and arguments
				message = self.getselected()
				msg,name = message[1][0].post, message[1][0].user
				if name[0] in "!#": name = name[1:]
				if self.bot.me:
					msg = msg.replace("@"+self.bot.me,"")
				self.text.append("@{}: `{}`".format(name, msg.replace('`',"")))
			except Exception as e: client.dbmsg(e)
			return 
		self.text.complete()
	
	def linklist(self):
		'''List accumulated links'''
		linksList = client.getLinks()

		#enter key
		def select(me):
			if not me.list: return
			current = linksList[len(me.list)-me.it-1] #this enforces the wanted link is selected
			client.open_link(self.parent,current,me.mode)
			if current not in self.bot.visited_links:
				self.bot.visited_links.append(current)
				self.parent.loop.create_task(self.recolorlines())
			#exit
			return -1

		def drawVisited(string,i,maxval):
			linksList = client.getLinks()
			current = linksList[maxval-i-1] #this enforces the wanted link is selected
			if current in self.bot.visited_links and self.parent.two56:
				string.insertColor(0,245 + self.parent.two56start)

		box = client.ListOverlay(self.parent,[i.replace("https://","").replace("http://","")
			for i in reversed(linksList)], drawVisited, client.getDefaults())
		box.addKeys({"enter":select
					,"tab": client.override(select)})
		box.add()

	def listmembers(self):
		'''List members of current group'''
		if self.bot.joinedGroup is None: return
		def select(me):
			current = me.list[me.it]
			current = current.split(' ')[0]
			if current[0] in "!#":
				current = current[1:]
			#reply
			self.text.append("@%s " % current)
			return -1
		def tab(me):
			current = me.list[me.it]
			current = current.split(' ')[0]
			if current not in self.bot.ignores:
				self.bot.ignores.append(current)
			else:

				self.bot.ignores.remove(current)
			self.redolines()

		users = self.bot.joinedGroup.userlist
		dispList = {i:users.count(i) for i in users}
		dispList = sorted([i+(j-1 and " (%d)"%j or "") for i,j in dispList.items()])
		def drawIgnored(string,i,maxval):
			selected = dispList[i]
			if selected.split(' ')[0] not in self.bot.ignores: return
			string[:-1]+'i'
			string.insertColor(-1,3)
		
		box = client.ListOverlay(self.parent,dispList,drawIgnored)
		box.addKeys({
			"enter":select
			,"tab":tab
		})
		box.add()

	def setformatting(self):
		'''Chatango formatting settings'''
		#select which further input to display
		def select(me):
			formatting = self.bot.creds["formatting"]
			furtherInput = None
			#ask for font color
			if me.it == 0:
				def selectSlide(me):
					formatting[0] = me.getHex()		#this is still by reference
					self.bot.setFormatting()
					return -1
					
				def enter(me):
					if me.it < 12:
						formatting[0] = me.getColor()
						self.bot.setFormatting()
						return -1
					else:
						me.openSliders(selectSlide)

				furtherInput = client.ColorOverlay(self.parent,formatting[0])
				furtherInput.addKeys({"enter":enter})
			#ask for name color
			elif me.it == 1:
				def selectSlide(me):
					formatting[1] = me.getHex()		#this is still by reference
					self.bot.setFormatting()
					return -1
					
				def enter(me):
					if me.it < 12:
						formatting[1] = me.getColor()
						self.bot.setFormatting()
						return -1
					else:
						me.openSliders(selectSlide)
			
				furtherInput = client.ColorOverlay(self.parent,formatting[1])
				furtherInput.addKeys({"enter":enter})
			#font face
			elif me.it == 2:
				def enter(me):
					formatting[2] = str(me.it)
					self.bot.setFormatting()
					return -1
				
				furtherInput = client.ListOverlay(self.parent,FONT_FACES)
				furtherInput.addKeys({"enter":enter})
				furtherInput.it = int(formatting[2])
			#ask for font size
			elif me.it == 3:
				def enter(me):
					formatting[3] = FONT_SIZES[me.it]
					self.bot.setFormatting()
					return -1
					
				furtherInput = client.ListOverlay(self.parent,list(map(str,FONT_SIZES)))
				furtherInput.addKeys({"enter":enter})
				furtherInput.it = FONT_SIZES.index(formatting[3])
			#insurance
			if furtherInput is None: raise Exception("How is this error even possible?")
			#add the overlay
			furtherInput.add()
			#set formatting, even if changes didn't occur
			
		box = client.ListOverlay(self.parent,["Font Color","Name Color","Font Face","Font Size"])
		box.addKeys({"enter":select})
		box.add()

	def setchannel(self):
		'''List channels'''
		def select(me):
			self.bot.channel = me.it
			return -1
		def ontab(me):
			self.bot.filtered_channels[me.it] = \
				 not self.bot.filtered_channels[me.it]
			self.redolines()
		def drawActive(string,i,maxval):
			if self.bot.filtered_channels[i]: return
			col = i and i+12 or 16
			string.insertColor(-1,col)
						
		box = client.ListOverlay(self.parent,["None","Red","Blue","Both"],drawActive)
		box.addKeys({
			"enter":select
			,"tab":	ontab
		})
		box.it = self.bot.channel
		box.add()

	def options(self):
		'''Options'''
		def select(me):
			if me.it == 0:		#mouse
				self.bot.options["mouse"] ^= 1
				self.parent.toggleMouse(self.bot.options["mouse"])
				pass
			elif me.it == 1:	#link opening
				def update(entry):
					try:
						self.bot.options["linkwarn"] = int(entry)
					except:	pass
				furtherInput = client.InputOverlay(self.parent, "Warning threshold "+\
					"for simultaneously opening links")
				furtherInput.runOnDone(update)
				furtherInput.add()
			elif me.it == 2:	#save ignores
				self.bot.options["ignoresave"] ^= 1
				if self.bot.options["ignoresave"]:
					creds_readwrite["ignores"] |= 2
				else:
					creds_readwrite["ignores"] &= ~2
					creds_entire["ignores"].clear()
			elif me.it == 3:	#bell on reply
				self.bot.options["bell"] ^= 1
			elif me.it == 4:	#256 colors
				self.bot.options["256color"] ^= 1
				self.parent.toggle256(self.bot.options["256color"])
				self.recolorlines()
			elif me.it == 5:	#html colors
				self.bot.options["htmlcolor"] ^= 1
				self.recolorlines()
			elif me.it == 6:	#colored anons
				self.bot.options["anoncolor"] ^= 1
				self.recolorlines()
			
		def drawOptions(string,i,maxval):
			if i == 0:		#mouse
				string[:-1]+(self.bot.options["mouse"] and "y" or "n")
				string.insertColor(-1,self.bot.options["mouse"] and 11 or 3)
			elif i == 1:	#link opening
				numlinks = str(self.bot.options["linkwarn"])
				startpos = -len(numlinks)
				string[:startpos]+numlinks
				string.insertColor(startpos,4)
			elif i == 2:	#save ignores
				string[:-1]+(self.bot.options["ignoresave"] and "y" or "n")
				string.insertColor(-1,self.bot.options["ignoresave"] and 11 or 3)
			elif i == 3:	#bell on reply
				string[:-1]+(self.bot.options["bell"] and "y" or "n")
				string.insertColor(-1,self.bot.options["bell"] and 11 or 3)
			elif i == 4:
				string[:-1]+(self.bot.options["256color"] and "y" or "n")
				string.insertColor(-1,self.bot.options["256color"] and 11 or 3)
			elif i == 5:
				string[:-1]+(self.bot.options["htmlcolor"] and "y" or "n")
				if (self.bot.options["256color"]):
					string.insertColor(-1,self.bot.options["htmlcolor"] and 11 or 3)
				elif self.parent.two56:
					string.insertColor(0,245 + self.parent.two56start)
			elif i == 6:
				string[:-1]+(self.bot.options["anoncolor"] and "y" or "n")
				if self.bot.options["256color"] and self.bot.options["htmlcolor"]:
					string.insertColor(-1,self.bot.options["anoncolor"] and 11 or 3)
				elif self.parent.two56:
					string.insertColor(0,245 + self.parent.two56start)

		box = client.ListOverlay(self.parent, OPTION_NAMES, drawOptions)
		box.addKeys({
			"enter":select
			,"tab":	select
			," ":	select
		})
		box.add()

	def addignore(self):
		'''Add ignore from selected message'''
		if self.isselecting():
			try:
				#allmessages contain the colored message and arguments
				message = self.getselected()
				name = message[1][0].user
				if name[0] in "!#": name = name[1:]
				if name in self.bot.ignores: return
				self.bot.ignores.append(name)
				self.redolines()
			except: pass
		return

	def reloadclient(self):
		'''Reload current group'''
		self.clear()
		self.bot.reconnect()

	def openlastlink(self):
		'''Open last link'''
		linksList = client.getLinks()
		if not linksList: return
		last = linksList[-1]
		client.open_link(self.parent,last)
		if last not in self.bot.visited_links:
			self.bot.visited_links.append(last)
			self.parent.loop.create_task(self.recolorlines())

	def joingroup(self):
		'''Join a new group'''
		inp = client.InputOverlay(self.parent,"Enter group name")
		inp.add()
		inp.runOnDone(lambda x: self.clear() or self.bot.changeGroup(x))

	def filterMessage(self, post, isreply, ishistory):
		return any((
				#filtered channels
				self.bot.filtered_channels[post.channel]
				#ignored users
				,post.user.lower() in self.bot.ignores
		))

	def colorizeMessage(self, msg, post, isreply, ishistory):
		rawWhite = client.rawNum(0)
		nameColor = rawWhite
		fontColor = rawWhite
		if not self.parent.two56 or not self.bot.options["htmlcolor"] or \
			(self.bot.options["anoncolor"] and post.user[0] in "#!"):
			nameColor = getColor(post.user)
			fontColor = getColor(post.user)
		elif self.parent.two56:
			base256 = self.parent.two56start
			nameColor = convertTo256(post.nColor, base256)
			fontColor = convertTo256(post.fColor, base256)

		#greentext, font color
		textColor = lambda x: x[0] == '>' and 11 or fontColor
		msg.colorByRegex(LINE_RE, textColor, group = 3)

		if self.parent.two56:
			#links in white
			linkColor = lambda x: (x in self.bot.visited_links and \
				 self.parent.two56) and (245 + base256) or rawWhite
			msg.colorByRegex(client.LINK_RE, linkColor, fontColor, 1)

		#underline quotes
		msg.effectByRegex(QUOTE_RE,1)

		#make sure we color the name right
		msg.insertColor(1, nameColor)
		#insurance the @s before a > are colored right
		#		space/username/:(space)
		msgStart = 1+len(post.user)+2
		if not msg.coloredAt(msgStart):
			msg.insertColor(msgStart,fontColor)
		if isreply:   msg.addGlobalEffect(0,1)
		if ishistory: msg.addGlobalEffect(1,1)
		#channel
		msg.insertColor(0,post.channel + 12)

LINE_RE = re.compile(r"^( [!#]?\w+?: (@\w* )*)?(.+)$",re.MULTILINE)
REPLY_RE = re.compile(r"@\w+?\b")
QUOTE_RE = re.compile(r"@\w+?: `[^`]+`")

#color by user's name
def getColor(name,init = 6,split = 109,rot = 6):
	if name[0] in "#!": name = name[1:]
	total = init
	for i in name:
		n = ord(i)
		total ^= (n > split) and n or ~n
	return (total+rot)%11

def convertTo256(string,base = 0):
	'''
	Convert a hex string to 256 color variant.
	Base denotes the position at which 256 colors are defined
	'''
	if string is None or len(string) < 3 or len(string) == 4:
		return client.rawNum(0)
	partsLen = len(string)//3
	in216 = [int(int(string[i*partsLen:(i+1)*partsLen],16)*6/(16**partsLen))
		 for i in range(3)]
	#too white or too black
	if sum(in216) < 2 or sum(in216) > 34:
		return client.rawNum(0)
	return base+16+sum(map(lambda x,y: x*y,in216,[36,6,1]))

def tabFile(path):
	'''A file tabbing utility'''
	findpart = path.rfind(os.path.sep)
	#offset how much we remove
	numadded = 0
	initpath,search = path[:findpart+1], path[findpart+1:]
	try:
		if not path or path[0] not in "~/": #try to generate full path
			newpath = os.path.join(os.getcwd(),initpath)
			ls = os.listdir(newpath)
		else:
			ls = os.listdir(os.path.expanduser(initpath))
	except (NotADirectoryError, FileNotFoundError):
		client.dbmsg("error occurred, aborting")
		return [],0
		
	suggestions = []
	if search: #we need to iterate over what we were given
		#insert \ for the suggestion parser
		suggestions = sorted([' ' in i and '"%s"' % (initpath+i).replace('"',r"\"")
			or (initpath+i).replace('"',r"\"") for i in ls if not i.find(search)])
	else: #otherwise ignore hidden files
		suggestions = sorted([' ' in i and '"%s"' % (initpath+i).replace('"','\"')
			or (initpath+i).replace('"',r"\"") for i in ls if i.find('.')])

	if not suggestions:
		return [],0
	return suggestions,-len(path) + numadded

#what it says on the tin
if ONLY_ONCE:
	#colors in this file because ChatangoOverlay depends on it directly
	#Non-256 colors
	ordering = \
		("blue"
		,"cyan"
		,"magenta"
		,"red"
		,"yellow")
	for i in range(10):
		client.defColor(ordering[i%5],intense=i//5) #0-10: legacy
	client.defColor("green",intense=True)
	client.defColor("green")			#11:	>
	client.defColor("none")				#12:	blank channel
	client.defColor("red","red")		#13:	red channel
	client.defColor("blue","blue")		#14:	blue channel
	client.defColor("magenta","magenta")#15:	both channel
	client.defColor("white","white")	#16:	blank channel, visible

	#COMMANDS-------------------------------------------------------------------
	@client.command("ignore")
	def ignore(parent,person,*args):
		chatOverlay = parent.getOverlaysByClassName("ChatangoOverlay")
		if not chatOverlay: return
		chatbot = chatOverlay[-1].bot

		if '@' == person[0]: person = person[1:]
		if person in chatbot.ignores: return
		chatbot.ignores.append(person)
		if chatOverlay: chatOverlay[-1].redolines()

	@client.command("unignore")
	def unignore(parent,person,*args):
		chatOverlay = parent.getOverlaysByClassName("ChatangoOverlay")
		if not chatOverlay: return
		chatbot = chatOverlay[-1].bot

		if '@' == person[0]: person = person[1:]
		if person == "all" or person == "everyone":
			chatbot.ignores.clear()
			if chatOverlay: chatOverlay[-1].redolines()
			return
		if person not in chatbot.ignores: return
		chatbot.ignores.remove(person)
		chatOverlay = parent.getOverlaysByClassName('ChatangoOverlay')
		if chatOverlay: chatOverlay[-1].redolines()

	@client.command("keys")
	def listkeys(parent,*args):
		'''Get list of the ChatangoOverlay's keys'''
		#keys are instanced at runtime
		chatOverlay = parent.getOverlaysByClassName("ChatangoOverlay")
		if not chatOverlay: return
		keysList = client.ListOverlay(parent,dir(chatOverlay[-1]))
		keysList.addKeys({
			"enter": lambda x: -1
		})
		return keysList

	@client.command("avatar",tabFile)
	def avatar(parent,*args):
		'''Upload the file as the user avatar'''
		chatOverlay = parent.getOverlaysByClassName("ChatangoOverlay")
		if not chatOverlay: return
		path = os.path.expanduser(' '.join(args))
		path = path.replace("\ ",' ')
		chatOverlay[-1].bot.uploadAvatar(path)

	ONLY_ONCE = False
