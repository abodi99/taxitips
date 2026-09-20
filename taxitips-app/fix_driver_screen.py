import re

with open('lib/screens/driver_screen.dart', 'r') as f:
    content = f.read()

# 1. Add _prefsSortModeKey
content = content.replace("static const _prefsPlaceKey = 'tb_filter_place';", 
                          "static const _prefsPlaceKey = 'tb_filter_place';\n  static const _prefsSortModeKey = 'tb_filter_sort_mode';")

# 2. Add _sortMode state
content = content.replace("bool _nearMe = false;", 
                          "bool _nearMe = false;\n  String _sortMode = 'score';")

# 3. Load sort mode
content = content.replace("final legacyPlace = prefs.getString(_prefsPlaceKey);",
                          "final legacyPlace = prefs.getString(_prefsPlaceKey);\n      final sortMode = prefs.getString(_prefsSortModeKey);")
content = content.replace("if (scoreMin != null) _scoreMin = scoreMin.clamp(0, 100);",
                          "if (sortMode != null) _sortMode = sortMode;\n        if (scoreMin != null) _scoreMin = scoreMin.clamp(0, 100);")

# 4. Save sort mode
content = content.replace("await prefs.setDouble(_prefsScoreMinKey, _scoreMin);",
                          "await prefs.setString(_prefsSortModeKey, _sortMode);\n      await prefs.setDouble(_prefsScoreMinKey, _scoreMin);")

# 5. Fix _sortByPriority
old_sort = """  void _sortByPriority(List<Map<String, dynamic>> list) {
    int rank(Map<String, dynamic> a) => switch (likelihoodForAlert(a)) {
      CustomerLikelihood.high => 0,
      CustomerLikelihood.medium => 1,
      CustomerLikelihood.low => 2,
    };
    list.sort((a, b) {
      final aActive = a['is_active'] != false;
      final bActive = b['is_active'] != false;
      if (aActive != bActive) return aActive ? -1 : 1;
      final ra = rank(a);
      final rb = rank(b);
      if (ra != rb) return ra.compareTo(rb);
      final sa =
          (a['worth_it_score'] as num?) ?? (a['demand_score'] as num?) ?? 0;
      final sb =
          (b['worth_it_score'] as num?) ?? (b['demand_score'] as num?) ?? 0;
      if (sa != sb) return sb.compareTo(sa);
      final da = (a['distance_km'] as num?)?.toDouble();
      final db = (b['distance_km'] as num?)?.toDouble();
      if (da != null && db != null && da != db) return da.compareTo(db);
      final ta = _signalTime(a);
      final tb = _signalTime(b);
      if (ta != null && tb != null && ta != tb) return tb.compareTo(ta);
      return _placeName(a).compareTo(_placeName(b));
    });
  }"""

new_sort = """  void _sortByPriority(List<Map<String, dynamic>> list) {
    int rank(Map<String, dynamic> a) => switch (likelihoodForAlert(a)) {
      CustomerLikelihood.high => 0,
      CustomerLikelihood.medium => 1,
      CustomerLikelihood.low => 2,
    };
    list.sort((a, b) {
      final aActive = a['is_active'] != false;
      final bActive = b['is_active'] != false;
      if (aActive != bActive) return aActive ? -1 : 1;

      final da = (a['distance_km'] as num?) ?? double.infinity;
      final db = (b['distance_km'] as num?) ?? double.infinity;
      final ta = (a['updated_at'] as String?) ?? '';
      final tb = (b['updated_at'] as String?) ?? '';

      if (_sortMode == 'score') {
        final sa = (a['worth_it_score'] as num?) ?? 0;
        final sb = (b['worth_it_score'] as num?) ?? 0;
        if (sa != sb) return sb.compareTo(sa);
      } else if (_sortMode == 'distance') {
        if (da != db) return da.compareTo(db);
      } else if (_sortMode == 'newest') {
        if (ta != tb) return tb.compareTo(ta);
      }

      final ra = rank(a);
      final rb = rank(b);
      if (ra != rb) return ra.compareTo(rb);
      if (da != db) return da.compareTo(db);
      return tb.compareTo(ta);
    });
  }"""
content = content.replace(old_sort, new_sort)

# 6. Add SegmentedButton in filters
filter_old = """                        ),
                        if (_filterableTiers.isNotEmpty)"""
filter_new = """                        ),
                        const SizedBox(height: 16),
                        const Text(
                          'Sortera listan',
                          style: TextStyle(fontWeight: FontWeight.w700),
                        ),
                        const SizedBox(height: 8),
                        SegmentedButton<String>(
                          style: SegmentedButton.styleFrom(
                            selectedBackgroundColor: TbColors.taxi,
                            selectedForegroundColor: TbColors.ink,
                          ),
                          segments: const [
                            ButtonSegment(value: 'score', label: Text('Poäng')),
                            ButtonSegment(value: 'distance', label: Text('Närmast')),
                            ButtonSegment(value: 'newest', label: Text('Nyast')),
                          ],
                          selected: {_sortMode},
                          onSelectionChanged: (set) => apply(() => _sortMode = set.first),
                        ),
                        if (_filterableTiers.isNotEmpty)"""
content = content.replace(filter_old, filter_new)

# NEW UX CHANGES
# 7. Top Bar Pill
top_bar_old = """                            Stack(
                              alignment: Alignment.center,
                              children: [
                                SvgPicture.asset(
                                  'assets/brand/logo.svg',
                                  height: 26,
                                ),
                                Row(
                                  mainAxisAlignment:
                                      MainAxisAlignment.spaceBetween,
                                  children: [
                                    if (widget.onBack != null)
                                      _MapButton(
                                        icon: Icons.arrow_back,
                                        tooltip: 'Tillbaka',
                                        size: 44,
                                        onTap: widget.onBack!,
                                      )
                                    else
                                      const SizedBox(width: 44),
                                    if (widget.onOpenSettings != null)
                                      _MapButton(
                                        icon: Icons.settings_outlined,
                                        tooltip: 'Inställningar',
                                        size: 44,
                                        onTap: widget.onOpenSettings!,
                                      )
                                    else
                                      const SizedBox(width: 44),
                                  ],
                                ),
                              ],
                            ),"""

top_bar_new = """                            Container(
                              padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 6),
                              decoration: BoxDecoration(
                                color: Colors.white.withOpacity(0.96),
                                borderRadius: BorderRadius.circular(32),
                                boxShadow: const [
                                  BoxShadow(
                                    color: Colors.black12,
                                    blurRadius: 12,
                                    offset: Offset(0, 4),
                                  ),
                                ],
                              ),
                              child: Stack(
                                alignment: Alignment.center,
                                children: [
                                  SvgPicture.asset(
                                    'assets/brand/logo.svg',
                                    height: 24,
                                  ),
                                  Row(
                                    mainAxisAlignment: MainAxisAlignment.spaceBetween,
                                    children: [
                                      if (widget.onBack != null)
                                        IconButton(
                                          icon: const Icon(Icons.arrow_back),
                                          tooltip: 'Tillbaka',
                                          color: TbColors.ink,
                                          onPressed: widget.onBack!,
                                        )
                                      else
                                        const SizedBox(width: 48),
                                      if (widget.onOpenSettings != null)
                                        IconButton(
                                          icon: const Icon(Icons.settings_outlined),
                                          tooltip: 'Inställningar',
                                          color: TbColors.ink,
                                          onPressed: widget.onOpenSettings!,
                                        )
                                      else
                                        const SizedBox(width: 48),
                                    ],
                                  ),
                                ],
                              ),
                            ),"""
content = content.replace(top_bar_old, top_bar_new)

# 8. Filter FAB & Location FAB
fab_old = """                      children: [
                        Badge(
                          isLabelVisible: _filtersActive,
                          smallSize: 12,
                          backgroundColor: TbColors.taxiDeep,
                          child: _MapButton(
                            icon: Icons.tune,
                            tooltip: 'Filter',
                            size: 56, // Större för enklare klick i farten
                            onTap: _openFilters,
                          ),
                        ),
                        _MapButton(
                          icon: _userLat != null
                              ? Icons.my_location
                              : Icons.location_searching,
                          tooltip: 'Min position',
                          size: 56,
                          iconColor: _userLat != null
                              ? const Color(0xFF1A73E8)
                              : TbColors.ink,
                          onTap: _goToMyLocation,
                        ),
                      ],"""

fab_new = """                      children: [
                        Badge(
                          isLabelVisible: _filtersActive,
                          smallSize: 12,
                          backgroundColor: TbColors.taxiDeep,
                          child: FloatingActionButton.extended(
                            heroTag: 'filter_fab',
                            onPressed: _openFilters,
                            backgroundColor: Colors.white,
                            foregroundColor: TbColors.ink,
                            elevation: 4,
                            icon: const Icon(Icons.tune),
                            label: const Text(
                              'Filter',
                              style: TextStyle(
                                fontSize: 16,
                                fontWeight: FontWeight.w700,
                              ),
                            ),
                          ),
                        ),
                        FloatingActionButton(
                          heroTag: 'location_fab',
                          onPressed: _goToMyLocation,
                          backgroundColor: Colors.white,
                          foregroundColor: _userLat != null
                              ? const Color(0xFF1A73E8)
                              : TbColors.ink,
                          elevation: 4,
                          child: Icon(
                            _userLat != null
                                ? Icons.my_location
                                : Icons.location_searching,
                          ),
                        ),
                      ],"""
content = content.replace(fab_old, fab_new)

# 9. Bottom Sheet Handle
handle_old = """                        return Material(
                          color: TbColors.vit,
                          elevation: 10,
                          shadowColor: Colors.black38,
                          borderRadius: const BorderRadius.vertical(
                            top: Radius.circular(24),
                          ),
                          clipBehavior: Clip.antiAlias,
                          child: RefreshIndicator(
                            color: TbColors.taxiDeep,
                            onRefresh: () => _load(),
                            child: ListView(
                              controller: scrollController,
                              physics: const AlwaysScrollableScrollPhysics(),
                              padding: EdgeInsets.only(
                                bottom:
                                    24 + MediaQuery.paddingOf(context).bottom,
                              ),
                              children: [
                                // Handtaget: tryck för att växla mellan lista och karta.
                                GestureDetector(
                                  behavior: HitTestBehavior.opaque,
                                  onTap: () => _expandSheet(
                                    _sheetExtent < 0.5 ? 0.9 : 0.42,
                                  ),
                                  child: Center(
                                    child: Container(
                                      margin: const EdgeInsets.fromLTRB(
                                        0,
                                        10,
                                        0,
                                        7,
                                      ),
                                      width: 44,
                                      height: 5,"""

handle_new = """                        return Material(
                          color: TbColors.vit,
                          elevation: 16,
                          shadowColor: Colors.black26,
                          borderRadius: const BorderRadius.vertical(
                            top: Radius.circular(32),
                          ),
                          clipBehavior: Clip.antiAlias,
                          child: RefreshIndicator(
                            color: TbColors.taxiDeep,
                            onRefresh: () => _load(),
                            child: ListView(
                              controller: scrollController,
                              physics: const AlwaysScrollableScrollPhysics(),
                              padding: EdgeInsets.only(
                                bottom: 24 + MediaQuery.paddingOf(context).bottom,
                              ),
                              children: [
                                // Handtaget: tryck för att växla mellan lista och karta.
                                GestureDetector(
                                  behavior: HitTestBehavior.opaque,
                                  onTap: () => _expandSheet(
                                    _sheetExtent < 0.5 ? 0.9 : 0.42,
                                  ),
                                  child: Center(
                                    child: Container(
                                      margin: const EdgeInsets.fromLTRB(0, 12, 0, 8),
                                      width: 64,
                                      height: 6,"""
content = content.replace(handle_old, handle_new)

# 10. _SheetTabs
tabs_old = """    return Container(
      padding: const EdgeInsets.all(4),
      decoration: BoxDecoration(
        color: TbColors.ljusgra,
        borderRadius: BorderRadius.circular(14),
      ),
      child: Row(
        children: [
          for (final (key, label, count) in tabs)
            Expanded(
              child: Semantics(
                button: true,
                selected: key == selected,
                label: '$label, $count',
                child: InkWell(
                  borderRadius: BorderRadius.circular(10),
                  onTap: () => onSelect(key),
                  child: AnimatedContainer(
                    duration: const Duration(milliseconds: 150),
                    height: 48,
                    alignment: Alignment.center,
                    decoration: BoxDecoration(
                      color: key == selected
                          ? TbColors.vit
                          : Colors.transparent,
                      borderRadius: BorderRadius.circular(10),
                      boxShadow: key == selected
                          ? const [
                              BoxShadow(
                                color: Color(0x22000000),
                                blurRadius: 4,
                                offset: Offset(0, 1),
                              ),
                            ]
                          : null,
                    ),
                    child: Text(
                      '$label $count',
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: TextStyle(
                        fontSize: 15,
                        fontWeight: key == selected
                            ? FontWeight.w800
                            : FontWeight.w600,
                        color: key == selected
                            ? TbColors.ink
                            : Colors.grey.shade700,
                      ),
                    ),
                  ),
                ),
              ),
            ),
        ],
      ),
    );"""

tabs_new = """    return Container(
      padding: const EdgeInsets.all(6),
      decoration: BoxDecoration(
        color: Colors.grey.shade200,
        borderRadius: BorderRadius.circular(16),
      ),
      child: Row(
        children: [
          for (final (key, label, count) in tabs)
            Expanded(
              child: Semantics(
                button: true,
                selected: key == selected,
                label: '$label, $count',
                child: InkWell(
                  borderRadius: BorderRadius.circular(12),
                  onTap: () => onSelect(key),
                  child: AnimatedContainer(
                    duration: const Duration(milliseconds: 150),
                    height: 52,
                    alignment: Alignment.center,
                    decoration: BoxDecoration(
                      color: key == selected ? Colors.white : Colors.transparent,
                      borderRadius: BorderRadius.circular(12),
                      boxShadow: key == selected
                          ? const [
                              BoxShadow(
                                color: Color(0x15000000),
                                blurRadius: 8,
                                offset: Offset(0, 2),
                              ),
                            ]
                          : null,
                    ),
                    child: Text(
                      '$label $count',
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: TextStyle(
                        fontSize: 16,
                        fontWeight: key == selected ? FontWeight.w800 : FontWeight.w600,
                        color: key == selected ? TbColors.ink : Colors.grey.shade600,
                      ),
                    ),
                  ),
                ),
              ),
            ),
        ],
      ),
    );"""
content = content.replace(tabs_old, tabs_new)

# 11. Remove _MapButton
map_btn_pattern = re.compile(r'class _MapButton extends StatelessWidget \{.*?\n\}\n', re.DOTALL)
content = map_btn_pattern.sub('', content)

# 12. Remove _signalTime
signal_time_pattern = re.compile(r'  String\? _signalTime\(Map<String, dynamic> a\) \{.*?\n  \}\n', re.DOTALL)
content = signal_time_pattern.sub('', content)

with open('lib/screens/driver_screen.dart', 'w') as f:
    f.write(content)

print("Done")
