#!/bin/bash
cd "$(dirname "$0")"
xattr -cr . 2>/dev/null || true
chmod +x ./*.command 2>/dev/null || true
chmod +x ./DropFile.pyw 2>/dev/null || true
./install_mac.command "$@"
