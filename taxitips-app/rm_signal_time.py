import re
with open('lib/screens/driver_screen.dart', 'r') as f:
    content = f.read()

signal_time_pattern = re.compile(r'  String\? _signalTime\(Map<String, dynamic> a\) \{.*?\n  \}\n', re.DOTALL)
content = signal_time_pattern.sub('', content)

with open('lib/screens/driver_screen.dart', 'w') as f:
    f.write(content)
print("Removed _signalTime")
