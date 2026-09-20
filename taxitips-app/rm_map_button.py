import re
with open('lib/screens/driver_screen.dart', 'r') as f:
    content = f.read()

# Remove _MapButton class
map_btn_pattern = re.compile(r'class _MapButton extends StatelessWidget \{.*?\n\}\n', re.DOTALL)
content = map_btn_pattern.sub('', content)

with open('lib/screens/driver_screen.dart', 'w') as f:
    f.write(content)
print("Removed _MapButton")
