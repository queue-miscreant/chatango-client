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
#TODO	get more messages from chatango callback
#		A way to sanity check the data is use the past[-1].time pulled
#		If less than, it's old data. If more than, it's new
#TODO	Messages dropping when ping coincides with message?
#TODO	Something with checking premature group removes

import chlib
import client
import sys
import os
import time
import re
import json

chatbot = None
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
			#write into safe credentials regardless
			creds_entire[i] = jsonData.get(i)
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

class ChatBot(chlib.ConnectionManager):
	'''Bot for interacting with the chat'''
	members = client.PromoteSet()

	def __init__(self,creds,parent):
		self.creds = creds
		self.channel = 0
		self.isinited = 0
		self.me = None
		self.joinedGroup = None
		self.mainOverlay = ChatangoOverlay(parent,self)
		self.mainOverlay.add()
		#new tabbing for members, ignoring the # and ! induced by anons and tempnames
		client.Tabber('@',self.members)
	
	def _start(self):
		self.isinited = 0
		self.members.clear()
		self.mainOverlay.parent.updateinfo(None,self.creds["user"])
		self.mainOverlay.msgSystem("Connecting")
		chlib.ConnectionManager.__init__(self, self.creds["user"], self.creds["passwd"], False)
		self.isinited = 1
		self.addGroup(self.creds["room"])
		
	def main(self):
		#wait until now to initialize the object, since now the information is guaranteed to exist
		self._start()
		chlib.ConnectionManager.main(self)
	
	def stop(self):
		if not self.isinited: return
		chlib.ConnectionManager.stop(self)
	
	def reconnect(self):
		if not self.isinited: return
		self.stop()
		self._start()
	
	def changeGroup(self,newgroup):
		self.stop()
		self.creds["room"] = newgroup
		self.addGroup(newgroup)

	def setFormatting(self):
		group = self.joinedGroup
		
		group.setFontColor(self.creds["formatting"][0])
		group.setNameColor(self.creds["formatting"][1])
		group.setFontFace(self.creds["formatting"][2])
		group.setFontSize(self.creds["formatting"][3])
		
		sendToFile(self.creds)
	
	def tryPost(self,text):
		if self.joinedGroup is None: return
		self.joinedGroup.sendPost(text,self.channel)
	
	def recvinited(self, group):
		self.mainOverlay.msgSystem("Connected to "+group.name)
		self.joinedGroup = group
		self.setFormatting()
		self.me = group.user
		if self.me in "!#": self.me = self.me[1:]
		#I modified the library to pull history messages, and put them in the group's message array
		#this organizes them by time and pushes the message
		past = sorted(group.pArray.values(),key=lambda x: x.time)
		for i in past:
			self.recvPost(group, i.user, i, 1)
		
		self.mainOverlay.msgTime(float(past[-1].time),"Last message at ")
		self.mainOverlay.msgTime()

	#on removal from a group
	def recvRemove(self,group):
		#self.parent.unget()
		self.stop()
		
	#on message
	def recvPost(self, group, user, post, ishistory = 0):
		#double check for anons
		if user[0] in '#!': user = user[1:]
		if user not in self.members:
			self.members.append(user.lower())
		self.members.promote(user.lower())
		#and is short-circuited
		isreply = self.me is not None and ('@'+self.me.lower() in post.post.lower())
		#sound bell
		if isreply and not ishistory: client.soundBell()
		#format as ' user: message' the space is for the channel
		msg = " {}: {}".format(post.user,post.post)
		client.parseLinks(msg)
		self.mainOverlay.msgPost(msg, user.lower(), isreply, ishistory, post.channel)
		#extra arguments. use in colorizers

	def recvshow_fw(self, group):
		self.mainOverlay.msgSystem("Flood ban warning issued")

	def recvshow_tb(self, group, secs):
		self.recvtb(group, secs)

	def recvtb(self, group, secs):
		self.mainOverlay.msgSystem("You are banned for %d seconds"%secs)
	
	#pull members when any of these are invoked
	def recvg_participants(self,group):
		self.members.extend(group.users)
		self.mainOverlay.parent.updateinfo(str(int(group.unum,16)))

	def recvparticipant(self, group, bit, user, uid):
		self.mainOverlay.parent.updateinfo(str(int(group.unum,16)))
		if user != "none":
			if (bit == '1'):
				self.members.append(user)
			#notifications
			self.mainOverlay.parent.newBlurb("%s has %s" % (user,(bit!='0') and "joined" or "left"))


#OVERLAY EXTENSION--------------------------------------------------------------------------------------
class ChatangoOverlay(client.MainOverlay):
	def __init__(self,parent,bot):
		client.MainOverlay.__init__(self,parent)
		self.bot = bot
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
	
	def openSelectedLinks(self):
		global visited_links
		try:
			message = self.getselected()
			msg = str(message[0])+' '
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
				client.ConfirmOverlay(self.parent,
					"Really open {} links? (y/n)".format(len(alllinks)),
					openall).add()
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
				msg = str(message[0])
				#first colon is separating the name from the message
				colon = msg.find(':')
				name = msg[1:colon]
				msg = msg[colon+2:]
				if name[0] in "!#":
					name = name[1:]
				self.text.append("@{}: `{}`".format(name,msg.replace('`',"")))
			except: pass
			return 
		self.text.complete()

	def linklist(self):
		'''List accumulated links'''
		#enter key
		def select(me):
			global visited_links
			if not client.getlinks(): return
			current = me.list[me.it].split(':')[0] #get the number selected, not the number by iterator
			current = client.getlinks()[int(current)-1] #this enforces the wanted link is selected
			client.open_link(self.parent,current,me.mode)
			if current not in visited_links:
				visited_links.append(current)
				self.recolorlines()
			#exit
			return -1

		box = client.ListOverlay(self.parent,client.reverselinks(),None,client.getdefaults())
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

		users = self.bot.joinedGroup.users
		dispList = {i:users.count(i) for i in users}
		dispList = sorted([i+(j-1 and " (%d)"%j or "") for i,j in dispList.items()])
		def drawIgnored(string,i):
			selected = dispList[i]
			if selected.split(' ')[0] not in ignores: return
			string[:-1]+'i'
			string.insertColor(-1,3)
		
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
			col = i and i+12 or 16
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
				msg = str(message[0])
				#first colon is separating the name from the message
				colon = msg.find(":")
				name = msg[1:colon]
				if name[0] in "!#":
					name = name[1:]
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
		if not client.getlinks(): return
		last = client.getlinks()[-1]
		client.open_link(self.parent,last)
		if last not in visited_links:
			visited_links.append(last)
			self.recolorlines()

	def joingroup(self):
		'''Join a new group'''
		inp = client.InputOverlay(self.parent,"Enter group name")
		inp.add()
		inp.runOnDone(lambda x: self.clear() or self.bot.changeGroup(x))

#COLORIZERS---------------------------------------------------------------------
#initialize colors
ordering = \
	("blue"
	,"cyan"
	,"magenta"
	,"red"
	,"yellow")
for i in range(10):
	client.defColor(ordering[i%5],i//5,isdim = dim_for_intense) #0-10: user text
client.defColor("green",True,isdim = dim_for_intense)
client.defColor("green",isdim = dim_for_intense)		#11: >meme arrow
client.defColor("none",False,"none",isdim = dim_for_intense)	#12-15: channels
client.defColor("red",False,"red",isdim = dim_for_intense)
client.defColor("blue",False,"blue",isdim = dim_for_intense)
client.defColor("magenta",False,"magenta",isdim = dim_for_intense)
client.defColor("white",False,"white",isdim = dim_for_intense)	#16: extra drawing
client.defColor("white",True,isdim = dim_for_intense)			#17: visited links

#color by user's name
def getColor(name,init = 6,split = 109,rot = 6):
	if name[0] in "#!": name = name[1:]
	total = init
	for i in name:
		n = ord(i)
		total ^= (n > split) and n or ~n
	return (total+rot)%11

@client.colorize
def defaultcolor(msg,*args):
	msg.default = getColor(args[0])

#color lines starting with '>' as green; ignore replies and ' user:'
LINE_RE = re.compile(r"^( [!#]?\w+?: )?(@\w* )*(.+)$",re.MULTILINE)
@client.colorize
def greentext(msg,*args):
	#match group 3 (the message sans leading replies)
	msg.colorByRegex(LINE_RE,lambda x: x[0] == ">" and 11 or None,3,"")

#color links white
@client.colorize
def link(msg,*args):
	msg.colorByRegex(client.LINK_RE,lambda x: (x not in visited_links) and client.rawNum(0) or 17,1)

#color replies by the color of the replier
REPLY_RE = re.compile(r"@\w+?\b")
@client.colorize
def names(msg,*args):
	def check(group):
		name = group.lower()[1:]
		if chatbot and name in chatbot.members:
			return getColor(name)
		return None
	msg.colorByRegex(REPLY_RE,check)

#underline quotes
QUOTE_RE = re.compile(r"`[^`]+`")
@client.colorize
def quotes(msg,*args):
	msg.effectByRegex(QUOTE_RE,1)
		
#draw replies, history, and channel
@client.colorize
def chatcolors(msg,*args):
	msg.insertColor(1)		#make sure we color the name right
	args[1] and msg.addGlobalEffect(0,1)	#reply
	args[2] and msg.addGlobalEffect(1,1)	#history
	msg.insertColor(0,args[3]+12)	#channel

#COMMANDS-----------------------------------------------------------------------------------------------
@client.command("ignore")
def ignore(parent,person,*args):
	global ignores
	if '@' == person[0]: person = person[1:]
	if person in ignores: return
	ignores.append(person)
	chatbot.mainOverlay.redolines()

@client.command("unignore")
def unignore(parent,person,*args):
	global ignores
	if '@' == person[0]: person = person[1:]
	if person == "all" or person == "everyone":
		ignores.clear()
		chatbot.mainOverlay.redolines()
		return
	if person not in ignores: return
	ignores.remove(person)
	chatbot.mainOverlay.redolines()

@client.command("keys")
def listkeys(parent,*args):
	'''Get list of the chatbot's keys'''
	keysList = client.ListOverlay(parent,dir(chatbot.mainOverlay))
	keysList.addKeys({
		"enter": lambda x: -1
	})
	return keysList

@client.command(client.CHAR_COMMAND)
def clientcommand(parent,*args):
	chatbot.sendCmd(*args)

#FILTERS------------------------------------------------------------------------------------------------
#filter filtered channels
@client.filter
def channelfilter(*args):
	try:
		return filtered_channels[args[3]]
	except:
		return True

@client.filter
def ignorefilter(*args):
	try:
		return args[0] in ignores
	except:
		return True
#-------------------------------------------------------------------------------------------------------

def runClient(main,creds):
	#fill in credential holes
	for num,i in enumerate(["user","passwd","room"]):
		#skip if supplied
		if creds.get(i) is not None: continue
		inp = client.InputOverlay(main,"Enter your " + ["username","password","room name"][num], num == 1,True)
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

	global chatbot
	#initialize chat bot
	chatbot = ChatBot(creds,main)
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
	try:
		client.start(runClient,newCreds)
	finally:
		if chatbot is not None:
			chatbot.stop()
