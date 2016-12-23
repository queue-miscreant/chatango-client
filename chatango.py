#!/usr/bin/env python3
#chatango.py:
'''
cube's chatango client
Usage:
	python chatango.py [options]:
	chatango [options]:

	Start the chatango client. 

Options:
	-c user pass:	Input credentials
	-g groupname:	Input group name
	-r:				Relog
	-nc:			No custom script import
	--help:			Display this page
'''
#TODO	Modifiable options like the threshold to ask to open links

import ch
import client
import sys
import os
import time
import re
import json

#entire creds from file
creds_entire = {} 
#writability of keys of creds
#1 = read only, 2 = write only, 3 = both
creds_readwrite = {
	 "user":	3
	,"passwd":	3
	,"room":	3
	,"formatting":	3
}
SAVE_PATH = os.path.expanduser("~/.chatango_creds")
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
DEFAULT_FORMATTING = \
	["DD9211"	#font color
	,"232323"	#name color
	,"0"		#font face
	,12]		#font size

#ignore list
#needed here so that commands can access it
ignores = []
filtered_channels = \
	[0	#white
	,0	#red
	,0	#blue
	,0] #both
visited_links = []
dim_for_intense = False

def readFromFile(readInto, filePath = SAVE_PATH):
	'''Read credentials from file'''
	global creds_entire
	try:
		jsonInput = open(filePath)
		jsonData = json.loads(jsonInput.read())
		jsonInput.close()
		for i,bit in creds_readwrite.items():
			if bit&1:
				readInto[i] = jsonData.get(i)
			#read into safe credentials regardless
			creds_entire[i] = jsonData.get(i)
	except FileNotFoundError:
		pass
	except Exception:
		raise IOError("Error reading creds! Aborting...")
def sendToFile(writeFrom,filePath = SAVE_PATH):
	'''Write credentials to file'''
	global creds_entire
	try:
		if filePath == "": return
		jsonData = {}
		for i,bit in creds_readwrite.items():
			if bit&2:
				jsonData[i] = writeFrom[i]
			else:	#"safe" credentials from last write
				jsonData[i] = creds_entire[i]
		encoder = json.JSONEncoder(ensure_ascii=False)
		out = open(filePath,'w')
		out.write(encoder.encode(jsonData)) 
	except Exception:
		raise IOError("Error writing creds! Aborting...")

def parsePost(post, me, ishistory):
	#and is short-circuited
	isreply = me is not None and ('@'+me.lower() in post.post.lower())
	#sound bell
	if isreply and not ishistory: client.soundBell()
	#format as ' user: message' the space is for the channel
	msg = " {}: {}".format(post.user,post.post)
	#links
	client.parseLinks(post.post, ishistory)
	#extra arguments. use in colorizers
	return (msg, post, isreply, ishistory)

class ChatBot(ch.Manager):
	'''Bot for interacting with the chat'''
	members = client.PromoteSet()

	def __init__(self,creds,parent):
		self.creds = creds
		self.channel = 0
		self.isinited = 0
		#default to the given user name
		self.me = creds.get("user") or None
		self.joinedGroup = None
		self.mainOverlay = ChatangoOverlay(parent,self)
		self.mainOverlay.add()
		#new tabbing for members, ignoring the # and ! induced by anons and tempnames
		client.Tokenize('@',self.members)
	
	def onInit(self):
		#wait until now to initialize the object, since now the information is guaranteed to exist
		if not self.isinited:
			self.isinited = 0
			super(ChatBot,self).__init__(self.creds["user"], self.creds["passwd"], False)
			self.isinited = 1
		self.mainOverlay.msgSystem("Connecting")
		self.members.clear()
		self.joinGroup(self.creds["room"])
	
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
		self.joinGroup(newgroup)

	def setFormatting(self):
		group = self.joinedGroup
		
		group.fColor = self.creds["formatting"][0]
		group.nColor = self.creds["formatting"][1]
		group.fFace = self.creds["formatting"][2]
		group.fSize = self.creds["formatting"][3]
		
		sendToFile(self.creds)
	
	def tryPost(self,text):
		if self.joinedGroup is None: return
		self.joinedGroup.sendPost(text,self.channel)
	
	def onConnect(self, group):
		self.mainOverlay.msgSystem("Connected to "+group.name)
		self.joinedGroup = group
		self.setFormatting()
		self.me = group.username
		if self.me[0] in "!#": self.me = self.me[1:]
		self.mainOverlay.parent.updateinfo(None,self.me)
		#show last message time
		self.mainOverlay.msgTime(group.last,"Last message at ")
		self.mainOverlay.msgTime()

	#on removal from a group
	def onLeave(self,group):
		#self.parent.unget()
		self.stop()
		
	#on message
	def onMessage(self, group, post):
		#double check for anons
		user = post.user
		if user[0] in '#!': user = user[1:]
		if user not in self.members:
			self.members.append(user.lower())
		msg = parsePost(post, self.me, False)

		self.members.promote(user.lower())
		self.mainOverlay.msgPost(*msg)

	def onHistoryDone(self, group, history):
		for post in history:
			user = post.user
			if user[0] in '#!': user = user[1:]
			if user not in self.members:
				self.members.append(user.lower())
			msg = parsePost(post, self.me, True)
			self.mainOverlay.msgPrepend(*msg)
		self.mainOverlay.canselect = True

	def onFloodWarning(self, group):
		self.mainOverlay.msgSystem("Flood ban warning issued")

	def onFloodBan(self, group, secs):
		self.onFloodBanRepeat(group, secs)

	def onFloodBanRepeat(self, group, secs):
		self.mainOverlay.msgSystem("You are banned for %d seconds"%secs)
	
	def onParticipants(self, group):
		self.members.extend(group.userlist)
		self.mainOverlay.recolorlines()

	def onUsercount(self, group):
		self.mainOverlay.parent.updateinfo(str(group.usercount))

	def onMemberJoin(self, group, user):
		if user != "anon":
			self.members.append(user)
		#notifications
		self.mainOverlay.parent.newBlurb("%s has joined" % user)

	def onMemberLeave(self, group, user):
		self.mainOverlay.parent.newBlurb("%s has left" % user)

	def onConnectionLost(self, group):
		message = self.mainOverlay.msgSystem("Connection lost; press any key to reconnect")
		def reconnect():
			self.mainOverlay.msgDelete(message)
			self.reconnect()
		client.BlockingOverlay(self.mainOverlay.parent,reconnect,"connect").add()


#OVERLAY EXTENSION--------------------------------------------------------------------------------------
class ChatangoOverlay(client.MainOverlay):
	def __init__(self,parent,bot):
		super(ChatangoOverlay, self).__init__(parent)
		self.bot = bot
		self.canselect = False
		self.addKeys({	"enter":	self.onenter
						,"a-enter":	self.onaltenter
						,"tab":		self.ontab
						,"f2":		self.linklist
						,"f3":		self.F3
						,"f4":		self.F4
						,"f5":		self.F5
						,"btab":	self.addignore
						,"^t":		self.joingroup
						,"^g":		self.openlastlink
						,"^r":		self.reloadclient
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
		global visited_links
		try:
			message = self.getselected()
			msg = message[1][0].post+' '
			alllinks = client.LINK_RE.findall(msg)
			def openall():
				recolor = False
				for i in alllinks:
					client.open_link(self.parent,i)
					if i not in visited_links:
						visited_links.append(i)
						recolor = True
				if recolor: self.recolorlines()
					
			if len(alllinks) > 1:
				self.parent.holdBlurb(
					"Really open {} links? (y/n)".format(len(alllinks)))
				client.ConfirmOverlay(self.parent, openall).add()
			else:
				openall()
		except Exception as exc: client.dbmsg(exc)

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
			global visited_links
			if not me.list: return
			current = linksList[len(me.list)-me.it-1] #this enforces the wanted link is selected
			client.open_link(self.parent,current,me.mode)
			if current not in visited_links:
				visited_links.append(current)
				self.recolorlines()
			#exit
			return -1

		def drawVisited(string,i):
			linksList = client.getLinks()
			current = linksList[-i-1] #this enforces the wanted link is selected
			if current in visited_links:
				string.insertColor(0,245)

		box = client.ListOverlay(self.parent,[i.replace("https://","").replace("http://","")
			for i in reversed(linksList)], drawVisited, client.getDefaults())
		#TODO better function composition
		box.addKeys({"enter":select
					,"tab":lambda x: select(x) and 0})
		box.add()

	def F3(self):
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
			global ignores
			current = me.list[me.it]
			current = current.split(' ')[0]
			if current not in ignores:
				ignores.append(current)
			else:
				ignores.remove(current)
			self.redolines()

		users = self.bot.joinedGroup.userlist
		dispList = {i:users.count(i) for i in users}
		dispList = sorted([i+(j-1 and " (%d)"%j or "") for i,j in dispList.items()])
		def drawIgnored(string,i):
			selected = dispList[i]
			if selected.split(' ')[0] not in ignores: return
			string[:-1]+'i'
			string.insertColor(-1,1)
		
		box = client.ListOverlay(self.parent,dispList,drawIgnored)
		box.addKeys({
			"enter":select
			,"tab":tab
		})
		box.add()

	def F4(self):
		'''Chatango formatting settings'''
		#select which further input to display
		def select(me):
			formatting = self.bot.creds["formatting"]
			furtherInput = None
			#ask for font color
			if me.it == 0:
				def enter(me):
					formatting[0] = me.getHex()	#this is still by reference
					self.bot.setFormatting()
					return -1

				furtherInput = client.ColorOverlay(self.parent,formatting[0])
				furtherInput.addKeys({"enter":enter})
			#ask for name color
			elif me.it == 1:
				def enter(me):
					formatting[1] = me.getHex()
					self.bot.setFormatting()
					return -1
			
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

	def F5(self):
		'''List channels'''
		def select(me):
			self.bot.channel = me.it
			return -1
		def ontab(me):
			global filtered_channels
			#space only
			filtered_channels[me.it] = not filtered_channels[me.it]
			self.redolines()
		def drawActive(string,i):
			if filtered_channels[i]: return
			col = i and i+256 or 260
			string.insertColor(-1,col)
						
		box = client.ListOverlay(self.parent,["None","Red","Blue","Both"],drawActive)
		box.addKeys({
			"enter":select
			,"tab":	ontab
		})
		box.it = self.bot.channel
		box.add()

	def addignore(self):
		if self.isselecting():
			global ignores
			try:
				#allmessages contain the colored message and arguments
				message = self.getselected()
				name = message[1][0].user
				if name[0] in "!#": name = name[1:]
				if name in ignores: return
				ignores.append(name)
				self.redolines()
			except: pass
		return

	def reloadclient(self):
		'''Reload current group'''
		self.clear()
		self.bot.reconnect()

	def openlastlink(self):
		'''Open last link'''
		global visited_links
		linksList = client.getLinks()
		if not linksList: return
		last = linksList[-1]
		client.open_link(self.parent,last)
		if last not in visited_links:
			visited_links.append(last)
			self.recolorlines()

	def joingroup(self):
		'''Join a new group'''
		inp = client.InputOverlay(self.parent,"Enter group name")
		inp.add()
		inp.runOnDone(lambda x: self.clear() or self.bot.changeGroup(x))

	def filterMessage(self, post, isreply, ishistory):
		return any((
				#filtered channels
				filtered_channels[post.channel]
				#ignored users
				,post.user.lower() in ignores
		))

	def colorizeMessage(self, msg, post, isreply, ishistory):
		nameColor = convertTo256(post.nColor)
		fontColor = convertTo256(post.fColor)

		#greentext, font color
		textColor = lambda x: x[0] == ">" and 2 or fontColor
		msg.colorByRegex(LINE_RE, textColor, group = 3)

		#links in white
		linkColor = lambda x: (x not in visited_links) and client.rawNum(0) or 245
		msg.colorByRegex(client.LINK_RE, linkColor, fontColor, 1)

		#underline quotes
		msg.effectByRegex(QUOTE_RE,1)

		#make sure we color the name right
		msg.insertColor(1, nameColor)
		#insurance the @s before a > are colored right
		msgStart = 1+len(post.user)+2
		if not msg.coloredAt(msgStart):
			msg.insertColor(msgStart,fontColor)
		if isreply:   msg.addGlobalEffect(0,1)
		if ishistory: msg.addGlobalEffect(1,1)
		#channel
		msg.insertColor(0,post.channel+256)

LINE_RE = re.compile(r"^( [!#]?\w+?: )?(@\w* )*(.+)$",re.MULTILINE)
REPLY_RE = re.compile(r"@\w+?\b")
QUOTE_RE = re.compile(r"`[^`]+`")

client.def256colors()				#0-255: regular colors
client.defColor("none")				#256:	blank channel
client.defColor("red","red")		#257:	red channel
client.defColor("blue","blue")		#258:	blue channel
client.defColor("magenta","magenta")#259:	both channel
client.defColor("white","white")	#260:	blank channel, visible

def convertTo256(string):
	if string is None or len(string) < 3 or len(string) == 4:
		return client.rawNum(0)
	partsLen = len(string)//3
	in216 = [int(int(string[i*partsLen:(i+1)*partsLen],16)*6/(16**partsLen))
		 for i in range(3)]
	if sum(in216) < 2 or sum(in216) > 34:
		return client.rawNum(0)
	return 16+sum(map(lambda x,y: x*y,in216,[36,6,1]))

#COMMANDS-----------------------------------------------------------------------------------------------
@client.command("ignore")
def ignore(parent,person,*args):
	global ignores
	if '@' == person[0]: person = person[1:]
	if person in ignores: return
	ignores.append(person)
	chatOverlay = parent.getOverlaysByClassName('ChatangoOverlay')
	if chatOverlay: chatOverlay[-1].redolines()

@client.command("unignore")
def unignore(parent,person,*args):
	global ignores
	if '@' == person[0]: person = person[1:]
	if person == "all" or person == "everyone":
		ignores.clear()
		chatOverlay = parent.getOverlaysByClassName('ChatangoOverlay')
		if chatOverlay: chatOverlay[-1].redolines()
		return
	if person not in ignores: return
	ignores.remove(person)
	chatOverlay = parent.getOverlaysByClassName('ChatangoOverlay')
	if chatOverlay: chatOverlay[-1].redolines()

@client.command("keys")
def listkeys(parent,*args):
	'''Get list of the ChatangoOverlay's keys'''
	chatOverlay = parent.getOverlaysByClassName('ChatangoOverlay')
	if not chatOverlay: return
	keysList = client.ListOverlay(parent,dir(chatOverlay[-1]))
	keysList.addKeys({
		"enter": lambda x: -1
	})
	return keysList

@client.command("avatar")
def avatar(parent,*args):
	'''Upload the file as the user avatar'''
	chatOverlay = parent.getOverlaysByClassName('ChatangoOverlay')
	if not chatOverlay: return
	path = os.path.expanduser(' '.join(args))
	client.dbmsg(chatOverlay[0].bot.uploadAvatar(path))

#-------------------------------------------------------------------------------------------------------
def runClient(main,creds):
	#fill in credential holes
	for num,i in enumerate(["user","passwd","room"]):
		#skip if supplied
		if creds.get(i) is not None: continue
		inp = client.InputOverlay(main,"Enter your " + \
			 ["username","password","room name"][num], num == 1,True)
		inp.add()
		creds[i] = inp.waitForInput()
		if not main.active: return
	#fill in formatting hole
	if creds.get("formatting") is None:
		#letting the program write into the constant would be stupid
		creds["formatting"] = []
		for i in DEFAULT_FORMATTING:
			creds["formatting"].append(i)
	elif isinstance(creds["formatting"],dict):	#backward compatible
		new = []
		for i in ["fc","nc","ff","fz"]:
			new.append(creds["formatting"][i])
		creds["formatting"] = new

	#initialize chat bot
	chatbot = ChatBot(creds,main)
	client.onDone(chatbot.stop)
	chatbot.main()

if __name__ == "__main__":
	newCreds = {}
	readCredsFlag = True
	importCustom = True
	credsArgFlag = 0
	groupArgFlag = 0
	
	for arg in sys.argv:
		#if it's an argument
		if arg[0] in '-':
			#stop creds parsing
			if credsArgFlag == 1:
				newCreds["user"] = ""
			if credsArgFlag <= 2:
				newCreds["passwd"] = ""
			if groupArgFlag:
				raise Exception("Improper argument formatting: -g without argument")
			credsArgFlag = 0
			groupArgFlag = 0

			if arg == "-c":			#creds inline
				creds_readwrite["user"] = 0		#no readwrite to user and pass
				creds_readwrite["passwd"] = 0
				credsArgFlag = 1
				continue	#next argument
			elif arg == "-g":		#group inline
				creds_readwrite["room"] = 2		#write only to room
				groupArgFlag = 1
				continue
			#arguments without subarguments
			elif arg == "-r":		#relog
				creds_readwrite["user"] = 2		#only write to creds
				creds_readwrite["passwd"] = 2
				creds_readwrite["room"] = 2
			elif arg == "-nc":		#no custom
				importCustom = False
			elif arg == "--help":	#help
				print(__doc__)
				sys.exit()
			
		if credsArgFlag:			#parse -c
			newCreds[ ["user","passwd"][credsArgFlag-1] ] = arg
			credsArgFlag = (credsArgFlag + 1) % 3

		if groupArgFlag:			#parse -g
			newCreds["room"] = arg
			groupArgFlag = 0

	if credsArgFlag >= 1:	#null name means anon
		newCreds["user"] = ""
	elif credsArgFlag == 2:	#null password means temporary name
		newCreds["passwd"] = ""
	if groupArgFlag:
		raise Exception("Improper argument formatting: -g without argument")

	readFromFile(newCreds)

	if importCustom:
		try:
			import custom #custom plugins
		except ImportError as exc: pass
	#start
	client.start(runClient,newCreds)
