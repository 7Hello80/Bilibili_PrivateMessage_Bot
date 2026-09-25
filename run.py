import time
import subprocess
import sys
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

class CodeChangeHandler(FileSystemEventHandler):
    def __init__(self, script_path):
        self.script_path = script_path
        self.process = None
        self.restart_process()
    
    def on_modified(self, event):
        if event.src_path.endswith('.py'):
            print(f"检测到文件变更: {event.src_path}")
            self.restart_process()
    
    def restart_process(self):
        if self.process:
            self.process.terminate()
            self.process.wait()
        
        print("重启程序...")
        self.process = subprocess.Popen([sys.executable, self.script_path])

if __name__ == "__main__":
    script_to_watch = "web_panel.py"  # 要监控的脚本
    
    event_handler = CodeChangeHandler(script_to_watch)
    observer = Observer()
    observer.schedule(event_handler, path=".", recursive=True)
    observer.start()
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
        if event_handler.process:
            event_handler.process.terminate()
    observer.join()