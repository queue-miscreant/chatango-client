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

Useful Key Bindings:
	F2:		Link accumulator
	F3:		List current group members
	F4:		Chat formatting menu
	F5:		Channels and filtering
	F12:	Options menu

	^G:		Open most recent link
	^R:		Refresh current group
	^T:		Switch to new group
'''
from util import chatango_client as cc
from util import client
import os
import sys
import json

CREDS_FILENAME = "chatango_creds"
CUSTOM_PATH = os.path.expanduser("~/.cubecli/")
DEPRECATED_SAVE_PATH = os.path.expanduser("~/.%s"%CREDS_FILENAME)
SAVE_PATH = CUSTOM_PATH+CREDS_FILENAME

#entire creds from file
creds_entire = {} 
#writability of keys of creds
#1 = read only, 2 = write only, 3 = both
creds_readwrite = {
	 "user":	3
	,"passwd":	3
	,"room":	3
	,"formatting":	3
	,"options":	3
	,"ignores":	1
	,"filtered_channels":	3
}
DEFAULT_OPTIONS = \
	{"mouse": 		False
	,"linkwarn":	2
	,"ignoresave":	False
	,"bell":		True
	,"256color":	True
	,"htmlcolor":	True
	,"anoncolor":	False}
DEFAULT_FORMATTING = \
	["DD9211"	#font color
	,"232323"	#name color
	,"0"		#font face
	,12]		#font size

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

@client.command("avatar",cc.tabFile)
def avatar(parent,*args):
	'''Upload the file as the user avatar'''
	chatOverlay = parent.getOverlaysByClassName("ChatangoOverlay")
	if not chatOverlay: return
	path = os.path.expanduser(' '.join(args))

#---------------------------------------------------------------------------
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

	#ignores hole
	if creds.get("ignores") is None:
		creds["ignores"] = []	#initialize it
	#filtered streams
	if creds.get("filtered_channels") is None:
		creds["filtered_channels"] = [0,0,0,0]
	#options
	if creds.get("options") is None:
		creds["options"] = {}
	for i in DEFAULT_OPTIONS:
		if creds["options"].get(i) is None:
			creds["options"][i] = DEFAULT_OPTIONS[i]

	main.toggleMouse(creds["options"]["mouse"])

	#initialize chat bot
	chatbot = cc.ChatBot(creds,main)
	client.onDone(chatbot.stop)
	chatbot.main()

def defineColors():
	#Non-256 colors
	ordering = \
		("blue"
		,"cyan"
		,"magenta"
		,"red"
		,"yellow")
	for i in range(10):
		client.defColor(ordering[i%5],intense=i//5) #0-10: legacy
	del ordering
	client.defColor("green",intense=True)
	client.defColor("green")			#11:	>
	client.defColor("none")				#12:	blank channel
	client.defColor("red","red")		#13:	red channel
	client.defColor("blue","blue")		#14:	blue channel
	client.defColor("magenta","magenta")#15:	both channel
	client.defColor("white","white")	#16:	blank channel, visible

if __name__ == "__main__":
	defineColors()
	#start everything up now
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
	
	#DEPRECATED, updating to current paradigm
	if os.path.exists(DEPRECATED_SAVE_PATH):
		import shutil
		os.mkdir(CUSTOM_PATH)
		os.mkdir(CUSTOM_PATH + os.path.sep + "custom")
		shutil.move(DEPRECATED_SAVE_PATH,SAVE_PATH)

	try:
		jsonInput = open(SAVE_PATH)
		jsonData = json.loads(jsonInput.read())
		jsonInput.close()
		for i,bit in creds_readwrite.items():
			if bit&1:
				newCreds[i] = jsonData.get(i)
			#read into safe credentials regardless
			creds_entire[i] = jsonData.get(i)
	except (FileNotFoundError, ValueError):
		pass
	except Exception as exc:
		raise IOError("Error reading creds! Aborting...") from exc

	#options
	two56colors = DEFAULT_OPTIONS["256color"]
	if newCreds.get("options"):
		if newCreds["options"]["ignoresave"]:
			creds_readwrite["ignores"] |= 2
		if newCreds["options"].get("256color") == False:
			two56colors = False

	if importCustom:
		sys.path.append(CUSTOM_PATH)
		try:
#			import custom
			from custom import *
		except ImportError: pass
	#start
	try:
		client.start(runClient,newCreds,two56=two56colors)
	finally:
		#save
		try:
			jsonData = {}
			for i,bit in creds_readwrite.items():
				if bit&2 or i not in creds_entire:
					jsonData[i] = newCreds[i]
				else:	#"safe" credentials from last write
					jsonData[i] = creds_entire[i]
			encoder = json.JSONEncoder(ensure_ascii=False)
			with open(SAVE_PATH,'w') as out:
				out.write(encoder.encode(jsonData)) 
		except KeyError:
			pass
		except Exception as exc:
			raise IOError("Error writing creds!") from exc
