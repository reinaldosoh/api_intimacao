# userinput.py - File-based input for Cascade terminal
import os
import time

INPUT_FILE = "cascade_input.txt"

def wait_for_input():
    """Wait for user to write input to cascade_input.txt"""
    # Clear/create the input file
    with open(INPUT_FILE, "w") as f:
        f.write("")
    
    print("prompt: (escreva sua instrução em cascade_input.txt e salve)")
    
    while True:
        time.sleep(0.5)
        if os.path.exists(INPUT_FILE):
            with open(INPUT_FILE, "r", encoding="utf-8") as f:
                content = f.read().strip()
            if content:
                return content

user_input = wait_for_input()
print(f"Recebido: {user_input}")