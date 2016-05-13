#!/usr/bin/env python3
#
#chatango.py:
#		Chat bot that extends the ConnectionManager class in chlib and
#		adds extensions to the client for chatango only.
#		The main source file.
#

import sys

if "--help" in sys.argv:
	print("""cube's chatango client
Usage:
	chatango [-c username password] [-g group]:	Start the chatango client. 

Options:
	-c:		Input credentials again
	-g:		Input group name again
	--help:		Display this page
	""")
	exit()
	
#try importing client
try:
	import client
	from client import dbmsg
except ImportError:
	print("ERROR WHILE IMPORTING CURSES, is this running on Windows cmd?")
	exit()
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

IMG_PATH = "feh"
MPV_PATH = "mpv"

#ignore list
#needed here so that commands can access it
ignores = []
filtered_channels = [0, #white
			0, #red
			0, #blue
			0] #both

def getColor(name,rot = 6,init = 6,split = 109):
	total = init
	for i in name:
		n = ord(i)
		total ^= (n > split) and n or ~n
	return (total+rot)%11

def init_colors():
	ordering = (
		'blue',
		'cyan',
		'magenta',
		'red',
		'yellow',
		)
	ordlen = 5
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
#format raw HTML data
def formatRaw(raw):
	if len(raw) == 0: return raw
	html = re.findall("(<[^<>]*?>)", raw)
	#REEEEEE CONTROL CHARACTERS GET OUT
	for j in raw:
		if ord(j) < 32:
			raw = raw.replace(j,"")
	#replace <br>s with actual line breaks
	#otherwise, remove html
	for i in html:
		raw = raw.replace(i,i == "<br/>" and "\n" or "")
	raw = decodeHtml(raw)
	#remove trailing \n's
	while len(raw) and raw[-1] == "\n":
		raw = raw[:-1]
	#thumbnail fix in chatango
	for i in re.finditer(r"(https?://ust.chatango.com/.+?/)t(_\d+.\w+)",raw):
		cap = i.regs[0]
		raw = raw[:cap[0]] + i.group(1) + 'l' + i.group(2) + raw[cap[1]:]

	return raw

#fucking HTML
def decodeHtml(raw,encode=0):
	htmlCodes = [["&#39;","'"],
		 ["&gt;",">"],
		 ["&lt;","<"],
		 ["&quot;",'"'],
		 ["&amp;",'&']]
	if encode: htmlCodes = reversed(htmlCodes)
	for i in htmlCodes:
		if encode: raw = raw.replace(i[1],i[0])
		else: raw = raw.replace(i[0],i[1])
	#decode nbsps
	if not encode:
		raw = raw.replace("&nbsp;"," ")
	
	return raw

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
class chat_bot(chlib.ConnectionManager):
	parent = None
	members = []

	def __init__(self,creds):
		self.creds = creds
		self.channel = 0
		
	def wrap(self,wrapper):
		self.parent = wrapper
		self.parent.chatBot = self
	
	def main(self):
		for num,i in enumerate(['user','passwd','room']):
			if creds.get(i):
				continue
			prompt = ['username', 'password', 'group name'][num]
			inp = client.inputOverlay("Enter your " + prompt, num == 1)
			self.parent.addOverlay(inp)
			creds[i] = inp.waitForInput();

		chlib.ConnectionManager.__init__(self, creds['user'], creds['passwd'], False)

		self.addGroup(creds['room'])
		chlib.ConnectionManager.main(self)

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
	
	def start(self,*args):
		self.parent.msgSystem('Connecting')
		self.parent.updateinfo(None,self.creds.get('user'))
	
	def tryPost(self,text):
		try:
			group = getattr(self,'joinedGroup')
			text = decodeHtml(text,1)
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

	def recvRemove(self,group):
		self.stop()

	#on disconnect
	def stop(self):
		chlib.ConnectionManager.stop(self)
		self.parent.active = False
		self.parent.unget()
		
	#on message
	def recvPost(self, group, user, post, history = 0):
		#post.ip contains channel info
		if user in ignores: return

		if user not in self.members:
			self.members.append(user)
		me = self.creds.get('user')
		#and is short-circuited
		reply = me is not None and ("@"+me.lower() in post.raw.lower())
		#sound bell
		if reply and not history: print('\a')
		#format as ' user: message'
		self.parent.msgPost("{}: {}".format(post.user,formatRaw(post.raw)),
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
@client.onkey("tab")
def ontab(self):
	#only search after the last space
	lastSpace = self.text().rfind(" ")
	search = self.text()[lastSpace + 1 and lastSpace:]
	#find the last @
	reply = search.rfind("@")
	if reply+1:
		afterReply = search[reply+1:]
		#look for the name starting with the text given
		if afterReply != "":
			#up until the @
			self.text.append(findName(afterReply,self.chatBot.members) + " ")

@client.onkey('KEY_F3')
def F3(self):
	#special wrapper to manipulate inject functionality for newlines in the list
	def select(me):
		def ret():
			current = me.list[me.it]
			current = current.split(' ')[0]
			if current[0] in "!#":
				current = current[1:]
			#reply
			self.text.append("@%s " % current)
			return -1
		return ret
	
	dispList = {i:self.chatBot.members.count(i) for i in self.chatBot.members}
	dispList = [str(i)+(j-1 and " (%d)"%j or "") for i,j in dispList.items()]
	box = client.listOverlay(sorted(dispList))
	box.addKeys({
		'enter':select(box),
	})
	
	self.addOverlay(box)

@client.onkey('KEY_F4')
def F4(self):
	#select which further input to display
	def select(me):
		def ret():
			formatting = self.chatBot.creds['formatting']
			furtherInput = None
			#ask for font color
			if me.it == 0:
				def enter(me):
					def ret():
						formatting['fc'] = client.toHexColor(me.color)
						self.chatBot.setFormatting(formatting)
						return -1
					return ret

				furtherInput = client.colorOverlay(client.fromHexColor(formatting['fc']))
				furtherInput.addKeys({
					'enter':enter(furtherInput),
				})
			#ask for name color
			elif me.it == 1:
				def enter(me):
					def ret():
						formatting['nc'] = client.toHexColor(me.color)
						self.chatBot.setFormatting(formatting)
						return -1
					return ret
			
				furtherInput = client.colorOverlay(client.fromHexColor(formatting['nc']))
				furtherInput.addKeys({
					'enter':enter(furtherInput),
				})
			#font face
			elif me.it == 2:
				def enter(me):
					def ret():
						formatting['ff'] = str(me.it)
						self.chatBot.setFormatting(formatting)
						return -1
					return ret
				
				furtherInput = client.listOverlay(FONT_FACES)
				furtherInput.addKeys({
					'enter':enter(furtherInput),
				})
				furtherInput.it = int(formatting['ff'])
			#ask for font size
			elif me.it == 3:
				def enter(me):
					def ret():
						formatting['fz'] = FONT_SIZES[me.it]
						self.chatBot.setFormatting(formatting)
						return -1
					return ret
					
				furtherInput = client.listOverlay([i for i in map(str,FONT_SIZES)])
				furtherInput.addKeys({
					'enter':enter(furtherInput),
				})
				furtherInput.it = FONT_SIZES.index(formatting['fz'])
			#insurance
			if furtherInput is None: raise Exception("How is this error even possible?")
			#add the overlay
			self.addOverlay(furtherInput)
			#set formatting, even if changes didn't occur
		return ret
		
	box = client.listOverlay(["Font Color", "Name Color", "Font Face", "Font Size"])
	box.addKeys({
		'enter':select(box),
	})
	
	self.addOverlay(box)

@client.onkey('KEY_F5')
def F5(self):
	def select(me):
		def ret():
			self.chatBot.channel = me.it
			return -1
		return ret
	
	def oninput(me):
		def ret(chars):
			global filtered_channels
			#space only
			if chars[0] != 32: return
			filtered_channels[me.it] = not filtered_channels[me.it]
		return ret
	
	def drawActive(string,i):
		string.insertColor(0,0,False)
		a = client._BOX_JUST(string())
		if filtered_channels[i]: return string.ljust(a)
		col = i and i+12 or 16
		string.ljust(a-1)
		string.insertColor(a-1,col)
		string.append(' ')
					
	box = client.listOverlay(["None", "Red", "Blue", "Both"],drawActive)
	box.addKeys({
		'enter':select(box),
		'input':oninput(box),
	})
	box.it = self.chatBot.channel
	
	self.addOverlay(box)

#-------------------------------------------------------------------------------------------------------
#COLORERS
#color by user's name
@client.colorer
def defaultcolor(msg,coldic,*args):
	msg.default = getColor(msg()[:msg().find(':')])

#color lines starting with '>' as green; ignore replies and ' user:'
#also color lines by default
@client.colorer
def greentext(msg,*args):
	lines = msg().split("\n") #don't forget to add back in a char
	tracker = 0
	for no,line in enumerate(lines):
		try:
			#user:
			begin = re.match(r"^\w+?: ",line).end(0)
			#@user
			reply = re.match(r"^@\w+? ",line[begin:])
			if reply: begin += reply.end(0)
			tracker += msg.insertColor(0)
		except:
			begin = 0
		
		if not len(line[begin:]): continue
		if line[begin] == ">":
			tracker += msg.insertColor(begin+tracker,11)
		else:
			tracker += msg.insertColor(begin+tracker)
		tracker += len(line)+1 #add in the newline

#links as white
@client.colorer
def link(msg,*args):
	tracker = 0
	linkre = re.compile("(https?://.+?\\.[^ \n]+)")
	find = linkre.search(msg())
	while find:
		begin,end = tracker+find.start(0),tracker+find.end(0)
		#find the most recent color
		last = client.findcolor(msg(),end)
		end += msg.insertColor(begin,0,False)
		tracker = msg.insertColor(end,last) + end
		find = linkre.search(msg()[tracker:])

		
#draw replies, history, and channel
@client.colorer
def chatcolors(msg,*args):
	msg.addEffect(0,args[1])
	msg.addEffect(1,args[2])
	msg.insertColor(0,0)
	msg.prepend(" ")
	msg.insertColor(0,args[3]+12)

#-------------------------------------------------------------------------------------------------------
#OPENERS
#start and daemonize feh (or replaced image viewing program)
@client.opener("jpeg")
@client.opener("jpg")
@client.opener("jpg:large")
@client.opener("png")
def images(cli,link,ext):
	cli.newBlurb("Displaying image... ({})".format(ext))
	args = [IMG_PATH, link]
	try:
		displayProcess = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
		display_thread = Thread(target = displayProcess.communicate)
		display_thread.daemon = True
		display_thread.start()
	except Exception as exc:
		raise Exception("failed to start image display")
	
#start and daemonize mpv (or replaced video playing program)
@client.opener("webm")
@client.opener("mp4")
@client.opener("gif")
def videos(cli,link,ext):
	cli.newBlurb("Playing video... ({})".format(ext))
	args = [MPV_PATH, link, "--pause"]
	try:
		displayProcess = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
		display_thread = Thread(target = displayProcess.communicate)
		display_thread.daemon = True
		display_thread.start()
	except Exception as exc:
		raise Exception("failed to start video display")

@client.opener("htmllink")
def linked(cli,link):
	cli.newBlurb("Opened new tab")
	#magic code to output stderr to /dev/null
	savout = os.dup(1)
	os.close(1)
	os.open(os.devnull, os.O_RDWR)
	try:
		open_new_tab(link)
	finally:
		os.dup2(savout, 1)

#-------------------------------------------------------------------------------------------------------
#COMMANDS

#methods like this can be used in the form /[commandname]
@client.command('ignore')
def ignore(cli,arglist):
	global ignores
	person = arglist[0]
	if '@' == person[1]: person = person[1:]
	if person in ignores: return
	ignores.append(person)

def unignore(cli,arglist):
	global ignores
	person = arglist[0]
	if '@' == person[1]: person = person[1:]
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
try:
	import custom #custom plugins
except ImportError as exc:
	dbmsg(exc)

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
			
	#initialize colors and chat bot
	init_colors()
	chatbot = chat_bot(creds)
	#start
	client.start(chatbot,chatbot.main)
