#!/usr/bin/env python3
'''Client package with customizable display and link opening capabilities.'''

from .base import override, Box, OverlayBase, Manager, KeyContainer
from .overlay import ListOverlay, VisualListOverlay \
	, ColorOverlay, ColorSliderOverlay, ConfirmOverlay, DisplayOverlay \
	, TabOverlay, InputOverlay, InputMux
from .chat import CommandOverlay, ChatOverlay, Message, add_message_scroller
from .util import Tokenize, tab_file
from .display import Coloring, colors

on_done = Manager.on_done
command = CommandOverlay.command
two56 = colors.two56
grayscale = colors.grayscale
