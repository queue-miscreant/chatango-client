from client.display import *
import chatango
a = chatango.overlay._colorizers

chatango.chatbot = type('whocares',(object,),{"members":  ['cubebert','namefag0','ayanamiko','chamomileable','gondolabigduck','drrindou']})

data = []
with open("coloringdata") as stringsfile:
	data.extend(stringsfile.read().split("\n"))

for b in data:
	c = coloring(b)
	for i in a:
		i(c,"cubebert",False,False,0)
	print('\n'.join(breaklines(str(c),20,'    ')[0]))
	print('\n'.join(c.breaklines(20,'    ')[0]))
	input()
