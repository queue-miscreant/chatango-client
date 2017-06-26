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
from lib import chatango_client as cc
from lib import client
import os
import os.path as path
import asyncio
import sys
import json

#custom and credential saving setup
CREDS_FILENAME = "chatango_creds"
HOME_DIR = path.expanduser('~')
CUSTOM_PATH = path.join(HOME_DIR,".cubecli")
#save
DEPRECATED_SAVE_PATH = path.join(HOME_DIR,".%s"%CREDS_FILENAME)
SAVE_PATH = path.join(CUSTOM_PATH,CREDS_FILENAME)
#init code to import everything in custom
CUSTOM_INIT = '''
#code ripped from stackoverflow questions/1057431
#ensures the `from custom import *` in chatango.py will import all python files
#in the directory

from os.path import dirname, basename, isfile
import glob
modules = glob.glob(dirname(__file__)+"/*.py")
__all__ = [basename(f)[:-3] for f in modules \
			if not f.endswith("__init__.py") and isfile(f)]
'''
IMPORT_CUSTOM = True

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

@asyncio.coroutine
def runClient(main,creds):
	#fill in credential holes
	for num,i in enumerate(["user","passwd","room"]):
		#skip if supplied
		if creds.get(i) is not None: continue
		inp = client.InputOverlay(main,"Enter your " + \
			 ["username","password","room name"][num], num == 1,True)
		inp.add()
		creds[i] = yield from inp.waitForInput()
		if creds[i] is None: main.stop()
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

if __name__ == "__main__":
	newCreds = {}
	importCustom = True
	readCredsFlag = True
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
			#creds inline
			if arg == "-c":
				creds_readwrite["user"] = 0		#no readwrite to user and pass
				creds_readwrite["passwd"] = 0
				credsArgFlag = 1
				continue	#next argument
			#group inline
			elif arg == "-g":
				creds_readwrite["room"] = 2		#write only to room
				groupArgFlag = 1
				continue
			#flags without arguments
			elif arg == "-r":		#relog
				creds_readwrite["user"] = 2		#only write to creds
				creds_readwrite["passwd"] = 2
				creds_readwrite["room"] = 2
			elif arg == "-nc":		#no custom
				importCustom = False
			elif arg == "--help":	#help
				print(__doc__)
				sys.exit()
		#parse -c
		if credsArgFlag:
			newCreds[ ["user","passwd"][credsArgFlag-1] ] = arg
			credsArgFlag = (credsArgFlag + 1) % 3
		#parse -g
		if groupArgFlag:
			newCreds["room"] = arg
			groupArgFlag = 0
	#anon and improper arguments
	if credsArgFlag >= 1:	#null name means anon
		newCreds["user"] = ""
	elif credsArgFlag == 2:	#null password means temporary name
		newCreds["passwd"] = ""
	if groupArgFlag:
		raise Exception("Improper argument formatting: -g without argument")

	#DEPRECATED, updating to current paradigm
	if path.exists(DEPRECATED_SAVE_PATH) or not path.exists(CUSTOM_PATH):
		import shutil
		os.mkdir(CUSTOM_PATH)
		customDir = path.join(CUSTOM_PATH,"custom")
		os.mkdir(customDir)
		with open(path.join(CUSTOM_PATH,"__init__.py"),"w") as a:
			a.write(CUSTOM_INIT)
	if path.exists(DEPRECATED_SAVE_PATH):
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
	
	#finally importing custom
	if IMPORT_CUSTOM:
		sys.path.append(CUSTOM_PATH)
		from custom import *

	#start
	main = client.Main(two56colors)
	try:
		cc.ChatBot(newCreds,main)
		main.start()
		main.loop.create_task(runClient(main,newCreds))
		main.loop.run_forever()
	finally:
		main.loop.run_until_complete(main.loop.shutdown_asyncgens())
		main.loop.close()
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
