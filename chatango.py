#!/usr/bin/env python3
#
#chatango.py:
#		Chat bot that extends the ConnectionManager class in chlib and
#		adds extensions to the client for chatango only.
#		The main source file.
#		TODO make file in ~ (hidden, starting with .)

import sys

if "--help" in sys.argv:
	print("""cube's chatango client
Usage:
	chatango [-c username password] [-g group]:	Start the chatango client. 

Options:
	-c:		Input credentials again
	-g:		Input group name again
	-nc:		No custom script import
	--help:		Display this page
	""")
	sys.exit()
	
import client
import chlib
from threading import Thread
import subprocess
import re
import json
import os
from webbrowser import open_new_tab

#constants for chatango
FONT_FACES = ["Arial",
		  "Comic Sans",
		  "Georgia",
		  "Handwriting",
		  "Impact",
		  "Palatino",
		  "Papyrus",
		  "Times New Roman",
		  "Typewriter",
		  ]
FONT_SIZES = [9,10,11,12,13,14]

HTML_CODES = [
	["&#39;","'"],
	["&gt;",">"],
	["<br/>","\n"],
	["&lt;","<"],
	["&quot;",'"'],
	["&apos;","'"],
	["&amp;",'&'],
]

IMG_PATH = "feh"
MPV_PATH = "mpv"
XML_TAGS_RE = re.compile("(<[^<>]*?>)")
THUMBNAIL_FIX_RE = re.compile(r"(https?://ust.chatango.com/.+?/)t(_\d+.\w+)")
REPLY_RE = re.compile(r"^@\w+? ")
USER_RE = re.compile(r"^[!#]?\w+?: ")

#ignore list
#needed here so that commands can access it
ignores = []
filtered_channels = [0, #white
			0, #red
			0, #blue
			0] #both

def init_colors():
	ordering = (
		'blue',
		'cyan',
		'magenta',
		'red',
		'yellow',
		)
	ordlen = len(ordering)
	for i in range(ordlen*2):
		client.definepair(ordering[i%ordlen],i//ordlen) #0-10: user text
	client.definepair('green',True)
	client.definepair('green')		#11: >meme arrow
	client.definepair('none',False,'none')	#12-15: channels
	client.definepair('red',False,'red')
	client.definepair('blue',False,'blue')
	client.definepair('magenta',False,'magenta')
	client.definepair('white',False,'white')	#16: extra drawing

#read credentials from file
def readFromFile(filePath):
	try:
		jsonInput = open(filePath)
		jsonData = json.loads(jsonInput.read())
		jsonInput.close()
		return jsonData
	except Exception as exc:
		return {} 
def sendToFile(filePath,jsonData):
	if filePath == '': return
	encoder = json.JSONEncoder(ensure_ascii=False)
	out = open(filePath,'w')
	out.write(encoder.encode(jsonData)) 
#the normal chatango library just takes out HTML without formatting it
#so I'm adding <br> to \n. This further gets converted by the client into multiple lines
def formatRaw(raw):
	if len(raw) == 0: return raw
	#REEEEEE CONTROL CHARACTERS GET OUT
	#replace <br>s with actual line breaks
	#otherwise, remove html
	for i in XML_TAGS_RE.findall(raw):
		raw = raw.replace(i,i == "<br/>" and "\n" or "")
	for i in HTML_CODES:
		raw = raw.replace(i[0],i[1])
	#remove trailing \n's
	while len(raw) and raw[-1] == "\n":
		raw = raw[:-1]
	#thumbnail fix in chatango
	raw = THUMBNAIL_FIX_RE.subn(r"\1l\2",raw)[0]

	return raw.replace("&nbsp;"," ")

#if given is at place 0 in the member name
#return rest of the member name or an empty string
def findName(given,memList):
	for i in memList:
		if i[0] in "!#":
			i = i[1:]
		if not i.find(given):
			return i[len(given):]
	return ""

#bot for interacting with chat
class chat_bot(chlib.ConnectionManager,client.botclass):
	members = []

	def __init__(self,creds):
		self.creds = creds
		self.channel = 0
		self.isinited = 0
		
	def main(self):
		for num,i in enumerate(['user','passwd','room']):
			#skip if supplied
			if self.creds.get(i):
				continue
			prompt = ['username', 'password', 'group name'][num]
			inp = client.inputOverlay("Enter your " + prompt, num == 1,True)
			self.parent.addOverlay(inp)
			self.creds[i] = inp.waitForInput()
			if not client.active: return

		#wait until now to initialize the object, since now the information is guaranteed to exist
		chlib.ConnectionManager.__init__(self, self.creds['user'], self.creds['passwd'], False)
		self.isinited = 1

		chlib.ConnectionManager.main(self)

	def start(self,*args):
		self.parent.msgSystem('Connecting')
		self.parent.updateinfo(None,self.creds.get('user'))
		self.addGroup(self.creds.get('room'))
	
	def stop(self):
		if not self.isinited: return
		chlib.ConnectionManager.stop(self)
	
	def reconnect(self):
		if not self.isinited: return
		self.stop()
		self.start()

	def setFormatting(self, newFormat = None):
		group = self.joinedGroup
		
		if newFormat is not None:
			self.creds['formatting'] = newFormat
		
		if self.creds.get('formatting') is None:
			self.creds['formatting'] = {'fc': "DD9211",
			'nc': "232323",
			'ff': "0",
			'fz': 12,
			}
		group.setFontColor(self.creds['formatting']['fc'])
		group.setNameColor(self.creds['formatting']['nc'])
		group.setFontFace(self.creds['formatting']['ff'])
		group.setFontSize(self.creds['formatting']['fz'])
		
		sendToFile('creds',self.creds)
	
	def tryPost(self,text):
		try:
			group = getattr(self,'joinedGroup')
			#replace HTML equivalents
			for i in reversed(HTML_CODES):
				text = text.replace(i[1],i[0])
			group.sendPost(text.replace("\n","<br/>"),self.channel)
		except AttributeError:
			return
	
	def recvinited(self, group):
		self.parent.msgSystem("Connected to "+group.name)
		self.joinedGroup = group
		self.setFormatting()
		#I modified the library to pull history messages, and put them in the group's message array
		#this organizes them by time and pushes the message
		past = group.pArray.values()
		past = sorted(past,key=lambda x: x.time)
		for i in past:
			self.recvPost(group, i.user, i, 1)
		
		self.parent.msgTime(float(past[-1].time),"Last message at ")
		self.parent.msgTime()

	#on disconnect
	def recvRemove(self,group):
		#self.parent.unget()
		self.stop()
		
	#on message
	def recvPost(self, group, user, post, history = 0):
		if user not in self.members:
			self.members.append(user)
		me = self.creds.get('user')
		#and is short-circuited
		reply = me is not None and ("@"+me.lower() in post.raw.lower())
		#sound bell
		if reply and not history: print('\a',end="")
		#format as ' user: message'
		self.parent.msgPost(user+': '+formatRaw(post.raw),
		#extra arguments. use in colorers
			post.user, reply, history, post.channel)

	def recvshow_fw(self, group):
		self.parent.msgSystem("Flood ban warning issued")

	def recvshow_tb(self, group, mins, secs):
		self.recvtb(group, mins, secs)

	def recvtb(self, group, mins, secs):
		self.parent.msgSystem("You are banned for %d seconds"%(60*mins+secs))
	
	#pull members when any of these are invoked
	def recvparticipant(self, group, bit, user, uid):
		self.members = group.users
		self.parent.updateinfo(str(int(group.unum,16)))
		if user == "none": user = "anon"
		bit = (bit == "1" and 1) or -1
		#notifications
		self.parent.newBlurb("%s has %s" % (user,bit+1 and "joined" or "left"))
	
	def recvg_participants(self,group):
		self.members = group.users
		self.parent.updateinfo(str(int(group.unum,16)))

#-------------------------------------------------------------------------------------------------------
#KEYS
@client.onkey("enter")
def onenter(self):
	if self.isselecting():
		try:
			message = self.getselect()
			msg = client.decolor(message[0])+' '
			alllinks = client.LINK_RE.findall(msg)
			def openall():
				for i in alllinks:
					client.link_opener(self.parent,i)
			if len(alllinks) > 1:
				self.parent.msgSystem('Really open %d links? (y/n)'%\
					len(alllinks))
				self.addOverlay(client.confirmOverlay(openall))
			else:
				openall()
		except Exception: pass
		return
	text = str(self.text)
	#if it's not just spaces
	if text.count(" ") != len(text):
		#add it to the history
		self.text.clear()
		self.text.appendhist(text)
		#call the send
		chatbot.tryPost(text)

@client.onkey("tab")
def ontab(self):
	if self.isselecting():
		try:
			#allmessages contain the colored message and arguments
			message = self.getselect()
			msg = client.decolor(message[0])
			#first colon is separating the name from the message
			msg = msg[msg.find(':')+2:]
			self.text.append('@{}: `{}`'.format(message[1][0],
				msg.replace('`','')))
		except: pass
		return 
	#only search after the last space
	lastSpace = str(self.text).rfind(" ")
	search = str(self.text)[lastSpace + 1 and lastSpace:]
	#find the last @
	reply = search.rfind("@")
	if reply+1:
		afterReply = search[reply+1:]
		#look for the name starting with the text given
		if afterReply != "":
			#up until the @
			self.text.append(findName(afterReply,chatbot.members) + " ")

@client.onkey('f3')
def F3(self):
	#special wrapper to manipulate inject functionality for newlines in the list
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

	dispList = {i:chatbot.members.count(i) for i in chatbot.members}
	dispList = sorted([str(i)+(j-1 and " (%d)"%j or "") for i,j in dispList.items()])
	def drawIgnored(string,i):
		if dispList[i].split(' ')[0] not in ignores: return
		string.insertColor(-1,3)
		string[:-1]+'i'
	
	box = client.listOverlay(sorted(dispList),drawIgnored)
	box.addKeys({
		'enter':select,
		'tab':tab,
	})
	
	self.addOverlay(box)

@client.onkey('f4')
def F4(self):
	#select which further input to display
	def select(me):
		formatting = chatbot.creds['formatting']
		furtherInput = None
		#ask for font color
		if me.it == 0:
			def enter(me):
				formatting['fc'] = client.toHexColor(me.color)
				chatbot.setFormatting(formatting)
				return -1

			furtherInput = client.colorOverlay(client.fromHexColor(formatting['fc']))
			furtherInput.addKeys({'enter':enter})
		#ask for name color
		elif me.it == 1:
			def enter(me):
				formatting['nc'] = client.toHexColor(me.color)
				chatbot.setFormatting(formatting)
				return -1
		
			furtherInput = client.colorOverlay(client.fromHexColor(formatting['nc']))
			furtherInput.addKeys({'enter':enter})
		#font face
		elif me.it == 2:
			def enter(me):
				formatting['ff'] = str(me.it)
				chatbot.setFormatting(formatting)
				return -1
			
			furtherInput = client.listOverlay(FONT_FACES)
			furtherInput.addKeys({'enter':enter})
			furtherInput.it = int(formatting['ff'])
		#ask for font size
		elif me.it == 3:
			def enter(me):
				formatting['fz'] = FONT_SIZES[me.it]
				chatbot.setFormatting(formatting)
				return -1
				
			furtherInput = client.listOverlay([i for i in map(str,FONT_SIZES)])
			furtherInput.addKeys({'enter':enter})
			furtherInput.it = FONT_SIZES.index(formatting['fz'])
		#insurance
		if furtherInput is None: raise Exception("How is this error even possible?")
		#add the overlay
		self.addOverlay(furtherInput)
		#set formatting, even if changes didn't occur
		
	box = client.listOverlay(["Font Color","Name Color","Font Face","Font Size"])
	box.addKeys({
		'enter':select,
	})
	
	self.addOverlay(box)

@client.onkey('f5')
def F5(self):
	def select(me):
		chatbot.channel = me.it
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
					
	box = client.listOverlay(["None","Red","Blue","Both"],drawActive)
	box.addKeys({
		'enter':select,
		'tab':ontab,
	})
	box.it = chatbot.channel
	
	self.addOverlay(box)

@client.onkey('^r')
def reloadclient(self):
	self.clearlines()
	chatbot.reconnect()

@client.onkey('^g')
def openlastlink(self):
	client.link_opener(self.parent,client.lastlinks[-1])

#-------------------------------------------------------------------------------------------------------
#COLORERS
#color by user's name
def getColor(name,rot = 6,init = 6,split = 109):
	total = init
	for i in name:
		n = ord(i)
		total ^= (n > split) and n or ~n
	return (total+rot)%11

@client.colorer
def defaultcolor(msg,coldic,*args):
	strmsg = str(msg)
	msg.default = getColor(strmsg[:strmsg.find(':')])

#color lines starting with '>' as green; ignore replies and ' user:'
#also color lines by default
@client.colorer
def greentext(msg,*args):
	lines = str(msg).split("\n") #don't forget to add back in a char
	tracker = 0
	for no,line in enumerate(lines):
		try:
			#user:
			begin = USER_RE.match(line).end(0)
			#ignore each @user
			reply = REPLY_RE.match(line[begin:])
			while reply:
				begin += reply.end(0)
				reply = REPLY_RE.match(line[begin:])
			tracker += msg.insertColor(0)
		except:
			begin = 0
		#try catch in case the length of the string past begin is zero
		try:
			if line[begin] == ">":
				tracker += msg.insertColor(begin+tracker,11)
			else:
				tracker += msg.insertColor(begin+tracker)
		except IndexError: pass
		finally:
			tracker += len(line)+1 #add in the newline

#links as white
@client.colorer
def link(msg,*args):
	tracker = 0
	find = client.LINK_RE.search(str(msg)+' ')
	while find:
		begin,end = tracker+find.start(0),tracker+find.end(0)
		#find the most recent color
		last = msg.findColor(begin)
		end += msg.insertColor(begin,0,False)
		tracker = msg.insertColor(end,last) + end
		find = client.LINK_RE.search(str(msg)[tracker:] + ' ')
		
#draw replies, history, and channel
@client.colorer
def chatcolors(msg,*args):
	msg.addEffect(0,args[1])
	msg.addEffect(1,args[2])
	msg.insertColor(0,0)
	' ' + msg 
	msg.insertColor(0,args[3]+12)

#-------------------------------------------------------------------------------------------------------
#OPENERS
#start and daemonize feh (or replaced image viewing program)
@client.opener(1,"jpeg")
@client.opener(1,"jpg")
@client.opener(1,"jpg:large")
@client.opener(1,"png")
def images(cli,link,ext):
	cli.newBlurb("Displaying image... ({})".format(ext))
	args = [IMG_PATH, link]
	try:
		displayProcess = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
		display_thread = Thread(target = displayProcess.communicate)
		display_thread.daemon = True
		display_thread.start()
	except:
		cli.newBlurb("No viewer %s found"%FEH_PATH)
	
#start and daemonize mpv (or replaced video playing program)
@client.opener(1,"webm")
@client.opener(1,"mp4")
@client.opener(1,"gif")
def videos(cli,link,ext):
	cli.newBlurb("Playing video... ({})".format(ext))
	args = [MPV_PATH, link, "--pause"]
	try:
		displayProcess = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
		display_thread = Thread(target = displayProcess.communicate)
		display_thread.daemon = True
		display_thread.start()
	except:
		cli.newBlurb("No player %s found"%MPV_PATH)

@client.opener(0)
def linked(cli,link):
	cli.newBlurb("Opened new tab")
	#magic code to output stderr to /dev/null
	savout = os.dup(1)	#get another header for stdout
	saverr = os.dup(2)	#get another header for stderr
	os.close(1)		#close stdout briefly because open_new_tab doesn't pipe stdout to null
	os.close(2)
	os.open(os.devnull, os.O_RDWR)	#open devnull for writing
	try:
		open_new_tab(link)	#do thing
	finally:
		os.dup2(savout, 1)	#reopen stdout
		os.dup2(saverr, 2)

#-------------------------------------------------------------------------------------------------------
#COMMANDS

#methods like this can be used in the form `[commandname]
@client.command('ignore')
def ignore(cli,arglist):
	global ignores
	person = arglist[0]
	if '@' == person[0]: person = person[1:]
	if person in ignores: return
	ignores.append(person)

@client.command('unignore')
def unignore(cli,arglist):
	global ignores
	person = arglist[0]
	if '@' == person[0]: person = person[1:]
	if person not in ignores: return
	ignores.pop(person)

#-------------------------------------------------------------------------------------------------------
#FILTERS

#filter filtered channels
@client.chatfilter
def channelfilter(*args):
	try:
		return filtered_channels[args[3]]
	except:
		return True

@client.chatfilter
def ignorefilter(*args):
	try:
		return args[0] in ignores
	except:
		return True
#-------------------------------------------------------------------------------------------------------

if __name__ == '__main__':
	creds = readFromFile('creds')

	formatting = creds.get('formatting')
	formatting = formatting == {} and None or formatting

	#0th arg is the program, -c is at minimum the first arg, followed by the second and third args username and password
	if len(sys.argv) >= 4 and '-c' in sys.argv:
		try:
			credpos = sys.argv.index('-c')
			creds['user'] = sys.argv[credpos+1]
			creds['passwd'] = sys.argv[credpos+2]
			if '-' in creds['user'] or '-' in creds['passwd']: raise Exception()
		except:
			raise Exception("Improper argument formatting")
	#same deal for group
	if len(sys.argv) >= 3 and '-g' in sys.argv:
		try:
			grouppos = sys.argv.index('-g')
			creds['room'] = sys.argv[grouppos+1]
			if '-' in creds['room']: raise Exception()
		except:
			raise Exception("Improper argument formatting")

	if '-nc' not in sys.argv:
		try:
			import custom #custom plugins
		except ImportError as exc: pass
			
	#initialize colors and chat bot
	init_colors()
	chatbot = chat_bot(creds)
	#start
	try:
		client.start(chatbot,chatbot.main)
	finally:
		chatbot.stop()
