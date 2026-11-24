#!/bin/sh
# PageBurrow for macOS, also usable from phones and tablets on the same Wi-Fi
# (iPhone, iPad, Android). The window shows the address to open and a PIN.
exec sh "$(dirname "$0")/Start-macOS.command" --lan "$@"
