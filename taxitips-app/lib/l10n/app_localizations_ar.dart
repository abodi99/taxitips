// ignore: unused_import
import 'package:intl/intl.dart' as intl;
import 'app_localizations.dart';

// ignore_for_file: type=lint

/// The translations for Arabic (`ar`).
class AppLocalizationsAr extends AppLocalizations {
  AppLocalizationsAr([String locale = 'ar']) : super(locale);

  @override
  String get alertFeedbackGotFare => 'حصلت على راكب';

  @override
  String get alertFeedbackNoCustomer => 'لا يوجد زبون';

  @override
  String get alertFeedbackQueued => 'تم الحفظ. سيُرسل عند توفر الشبكة.';

  @override
  String get alertFeedbackSaveFailed => 'تعذّر حفظ إجابتك. حاول مرة أخرى.';

  @override
  String get alertFeedbackThanks => 'شكراً!';

  @override
  String get alertFeedbackTitle => 'كيف كانت النتيجة؟';

  @override
  String get categoryBarAll => 'الكل';

  @override
  String get categoryBarSaved => 'المحفوظ';

  @override
  String get companySettingsActiveTitle => 'نشط';

  @override
  String get companySettingsAdd => 'إضافة';

  @override
  String get companySettingsAddCar => 'إضافة سيارة';

  @override
  String get companySettingsAlreadyConnected => 'مرتبط بالفعل';

  @override
  String get companySettingsBlock => 'حظر';

  @override
  String get companySettingsBlockBody =>
      'يتوقف الهاتف عن عرض التنبيهات فورًا ويغادر السيارة. يحتاج السائق إلى دعوة جديدة للعودة.';

  @override
  String get companySettingsBlockPhone => 'حظر الهاتف';

  @override
  String companySettingsBlockTitle(String label) {
    return 'حظر $label؟';
  }

  @override
  String get companySettingsCancel => 'إلغاء';

  @override
  String get companySettingsCar => 'سيارة';

  @override
  String companySettingsCarAdded(String plate) {
    return 'تمت إضافة $plate';
  }

  @override
  String get companySettingsCarMissingOnLicense =>
      'السيارة غير موجودة في الترخيص. تواصل مع الدعم.';

  @override
  String companySettingsCarRemoved(String plate) {
    return 'تمت إزالة $plate';
  }

  @override
  String companySettingsCars(int used, int limit) {
    String _temp0 = intl.Intl.pluralLogic(
      limit,
      locale: localeName,
      other: 'سيارة',
      many: 'سيارة',
      few: 'سيارات',
      two: 'سيارتين',
      one: 'سيارة',
      zero: 'سيارات',
    );
    return '$used من $_temp0';
  }

  @override
  String get companySettingsCarsLabel => 'السيارات';

  @override
  String companySettingsChangeAgainNextMonth(String label) {
    return '$label\nيمكنك تغيير المقاطعة مرة أخرى الشهر القادم.';
  }

  @override
  String companySettingsChangeUsesOne(String label) {
    return '$label. كل تغيير يستخدم واحدًا منها.';
  }

  @override
  String get companySettingsCouldNotReadCompany => 'تعذّر تحميل بيانات الشركة.';

  @override
  String companySettingsCountyChangesLeft(int remaining, int total) {
    return 'تغييرات المقاطعة المتبقية هذا الشهر: $remaining من $total';
  }

  @override
  String get companySettingsCountyNotChangeable =>
      'لا يمكن تغيير المقاطعة من التطبيق.';

  @override
  String get companySettingsCountyWhereCarDrives =>
      'المقاطعة التي تعمل فيها السيارة';

  @override
  String companySettingsDaysLeft(int days) {
    String _temp0 = intl.Intl.pluralLogic(
      days,
      locale: localeName,
      other: 'بقي $days يوم',
      many: 'بقي $days يومًا',
      few: 'بقيت $days أيام',
      two: 'بقي يومان',
      one: 'بقي يوم واحد',
      zero: 'لم يتبق أيام',
    );
    return '$_temp0';
  }

  @override
  String get companySettingsDriveMyself => 'أعمل بنفسي بهذا الهاتف';

  @override
  String get companySettingsDriver => 'سائق';

  @override
  String get companySettingsDriverEmail => 'البريد الإلكتروني للسائق';

  @override
  String get companySettingsDriverEmailError =>
      'اكتب البريد الإلكتروني للسائق، مثلاً name@example.com';

  @override
  String get companySettingsDriverName => 'اسم السائق';

  @override
  String get companySettingsDriverNameOptional => 'اسم السائق (اختياري)';

  @override
  String get companySettingsDrivers => 'السائقون';

  @override
  String companySettingsDriversCount(int count) {
    String _temp0 = intl.Intl.pluralLogic(
      count,
      locale: localeName,
      other: '$count سائق',
      many: '$count سائقًا',
      few: '$count سائقين',
      two: 'سائقان',
      one: 'سائق واحد',
      zero: 'لا سائقين',
    );
    return '$_temp0';
  }

  @override
  String companySettingsDrivingBy(String name) {
    return 'السائق: $name';
  }

  @override
  String get companySettingsDrivingNow => 'يعمل الآن';

  @override
  String companySettingsGraceLine(String date) {
    return 'تعمل التنبيهات حتى $date.';
  }

  @override
  String get companySettingsGraceTitle => 'ستتوقف العضوية قريبًا';

  @override
  String get companySettingsInviteByEmail =>
      'ادعُ سائقًا عبر البريد الإلكتروني';

  @override
  String get companySettingsInviteDriverBody =>
      'يصل السائق بريد إلكتروني، ويختار كلمة مرور ويسجّل الدخول إلى التطبيق. عندها يُربط الهاتف بالسيارة.';

  @override
  String companySettingsInviteDriverTitle(String plate) {
    return 'دعوة سائق إلى $plate';
  }

  @override
  String get companySettingsInviteExpired => 'انتهت صلاحية الدعوة';

  @override
  String get companySettingsInviteRemoved => 'تمت إزالة الدعوة';

  @override
  String companySettingsInviteResent(String email) {
    return 'تم إرسال الدعوة مرة أخرى إلى $email';
  }

  @override
  String companySettingsInviteSent(String email) {
    return 'تم إرسال الدعوة إلى $email';
  }

  @override
  String companySettingsInvitedCount(int count) {
    String _temp0 = intl.Intl.pluralLogic(
      count,
      locale: localeName,
      other: '$count مدعو',
      many: '$count مدعوًا',
      few: '$count مدعوين',
      two: 'مدعوان',
      one: 'مدعو واحد',
      zero: 'لا مدعوين',
    );
    return '$_temp0';
  }

  @override
  String get companySettingsInvitedNotLoggedIn =>
      'تمت دعوته · لم يسجّل الدخول بعد';

  @override
  String get companySettingsLastDay => 'اليوم الأخير';

  @override
  String get companySettingsLoadFailedPull =>
      'تعذّر تحميل بيانات الشركة الآن. اسحب للأسفل للمحاولة مرة أخرى.';

  @override
  String get companySettingsMonthsShort =>
      'يناير,فبراير,مارس,أبريل,مايو,يونيو,يوليو,أغسطس,سبتمبر,أكتوبر,نوفمبر,ديسمبر';

  @override
  String get companySettingsMore => 'المزيد';

  @override
  String get companySettingsNameHint => 'مثلاً أحمد';

  @override
  String get companySettingsNoCars => 'لا توجد سيارات';

  @override
  String get companySettingsNoChangesLeft =>
      'لا توجد تغييرات مقاطعة متبقية هذا الشهر.';

  @override
  String get companySettingsNoCounty => 'لا توجد مقاطعة';

  @override
  String get companySettingsNoDriver => 'لا يوجد سائق';

  @override
  String get companySettingsNoDriverConnected => 'لا يوجد سائق مرتبط';

  @override
  String companySettingsNowDrives(String plate) {
    return 'هذا الهاتف يعمل الآن على $plate';
  }

  @override
  String companySettingsNowDrivesIn(String plate, String county) {
    return '$plate تعمل الآن في $county';
  }

  @override
  String get companySettingsOnlyAdminChanges =>
      'يمكن للمسؤول فقط تغيير المقاطعة.';

  @override
  String companySettingsPairedPickCar(String plate) {
    return 'تم ربط الهاتف بالسيارة $plate. اختر السيارة من القائمة.';
  }

  @override
  String get companySettingsPausedTitle => 'متوقف مؤقتًا';

  @override
  String get companySettingsPhoneBlocked => 'تم حظر الهاتف';

  @override
  String get companySettingsPlateLabel => 'رقم اللوحة';

  @override
  String get companySettingsRemove => 'إزالة';

  @override
  String get companySettingsRemoveCar => 'إزالة السيارة';

  @override
  String get companySettingsRemoveCarBody =>
      'يتوقف سائقو السيارة عن تلقي التنبيهات فورًا. ويصبح المقعد في الفترة التجريبية شاغرًا.';

  @override
  String companySettingsRemoveCarTitle(String plate) {
    return 'إزالة $plate؟';
  }

  @override
  String get companySettingsRename => 'تغيير الاسم';

  @override
  String companySettingsRenewsLine(String date) {
    return 'تُجدَّد في $date';
  }

  @override
  String get companySettingsResendInvite => 'إرسال مرة أخرى';

  @override
  String get companySettingsRetry => 'حاول مرة أخرى';

  @override
  String companySettingsRevokeBody(String email) {
    return 'لن يتمكن $email من استخدام الدعوة لتسجيل الدخول.';
  }

  @override
  String get companySettingsRevokeInvite => 'إزالة الدعوة';

  @override
  String get companySettingsRevokeTitle => 'إزالة الدعوة؟';

  @override
  String get companySettingsSave => 'حفظ';

  @override
  String get companySettingsSendInvite => 'إرسال الدعوة';

  @override
  String get companySettingsSuspendedLine => 'تواصل معنا في المحادثة.';

  @override
  String get companySettingsSuspendedTitle => 'موقوف';

  @override
  String get companySettingsTapToChangeCounty => 'اضغط لتغيير المقاطعة';

  @override
  String get companySettingsTheCar => 'السيارة';

  @override
  String get companySettingsThePhone => 'الهاتف';

  @override
  String get companySettingsThisPhone => 'هذا الهاتف';

  @override
  String get companySettingsTipsPaused => 'التنبيهات متوقفة مؤقتًا.';

  @override
  String get companySettingsTrialAllIncluded =>
      'كل ما في التطبيق متاح خلال الفترة التجريبية.';

  @override
  String companySettingsTrialContinuesLine(String until, String cars) {
    return 'تستمر العضوية بعد الفترة التجريبية · $until · $cars';
  }

  @override
  String get companySettingsTrialEndedTitle => 'انتهت الفترة التجريبية';

  @override
  String companySettingsTrialLine(String until, String cars) {
    return '$until · $cars';
  }

  @override
  String get companySettingsTrialLockedNotIncluded =>
      'ما عليه قفل في التطبيق غير مشمول في الفترة التجريبية.';

  @override
  String companySettingsTrialPendingLine(String cars) {
    return 'تبدأ عند ربط أول هاتف · $cars';
  }

  @override
  String get companySettingsTrialTitle => 'الفترة التجريبية';

  @override
  String companySettingsTrialUntil(String date) {
    return 'الفترة التجريبية سارية حتى $date.';
  }

  @override
  String get companySettingsWhereDoesCarDrive => 'أين تعمل السيارة؟';

  @override
  String get companySettingsYourCompany => 'شركتك';

  @override
  String get countyChecklistAllCounties =>
      'تظهر لك التنبيهات من كل مقاطعات العضوية. أزل العلامة عن التي لا تريد رؤيتها.';

  @override
  String get countyChecklistChangeTrialCounty =>
      'تغيير مقاطعة الفترة التجريبية';

  @override
  String get countyChecklistDone => 'تم';

  @override
  String get countyChecklistNoCounties => 'لا توجد مقاطعات في العضوية بعد.';

  @override
  String countyChecklistSomeCounties(int selected, int total) {
    return 'تظهر لك التنبيهات من $selected من أصل $total مقاطعة.';
  }

  @override
  String get countyChecklistTitle => 'مقاطعاتك';

  @override
  String get driverScreenAccessInactive => 'الوصول غير مفعّل.';

  @override
  String get driverScreenAllCountiesSelected =>
      'تم اختيار كل مقاطعاتك. ألغِ تحديد التي لا تريد رؤيتها.';

  @override
  String get driverScreenAllTips => 'كل النصائح';

  @override
  String driverScreenAllYourCounties(int count) {
    return 'كل مقاطعاتك ($count)';
  }

  @override
  String get driverScreenArea => 'المنطقة';

  @override
  String get driverScreenBack => 'رجوع';

  @override
  String get driverScreenBlockedBody => 'تواصل مع دعم TaxiTips.';

  @override
  String get driverScreenBlockedTitle => 'الحساب معلّق';

  @override
  String get driverScreenCalm => 'هادئ الآن';

  @override
  String get driverScreenCancelled => 'تم الإلغاء';

  @override
  String driverScreenCategoryLocked(String category) {
    return '$category غير مشمولة في الفترة التجريبية';
  }

  @override
  String get driverScreenChoose => 'اختر';

  @override
  String get driverScreenChooseAreaText => 'اختر منطقة قيادتك لرؤية النصائح.';

  @override
  String get driverScreenChooseCar => 'اختر السيارة التي تقودها لرؤية النصائح.';

  @override
  String get driverScreenChooseCarAction => 'اختر سيارة';

  @override
  String get driverScreenChooseCarFirstCounties =>
      'اختر سيارة أولًا. ستظهر مقاطعات السيارة هنا.';

  @override
  String get driverScreenClear => 'مسح';

  @override
  String get driverScreenClearFilters => 'مسح التصفية';

  @override
  String get driverScreenConnectingPhone => 'جارٍ ربط الهاتف…';

  @override
  String get driverScreenCountiesAndMunicipalities => 'المقاطعات والبلديات';

  @override
  String get driverScreenDayToday => 'اليوم';

  @override
  String get driverScreenDayTomorrow => 'غدًا';

  @override
  String get driverScreenDayWeekend => 'عطلة نهاية الأسبوع';

  @override
  String driverScreenDays(int count) {
    String _temp0 = intl.Intl.pluralLogic(
      count,
      locale: localeName,
      other: '$count يوم',
      many: '$count يومًا',
      few: '$count أيام',
      two: 'يومان',
      one: 'يوم واحد',
    );
    return '$_temp0';
  }

  @override
  String get driverScreenDone => 'تم';

  @override
  String get driverScreenDrivingArea => 'منطقة القيادة';

  @override
  String get driverScreenDrivingAreaText =>
      'المقاطعات التي تعمل فيها. الإشعارات والقائمة (عندما لا يعرف التطبيق موقعك) تتبع منطقة القيادة.';

  @override
  String get driverScreenEvents => 'الفعاليات';

  @override
  String get driverScreenEventsFailed => 'لا يمكن جلب الفعاليات الآن.';

  @override
  String get driverScreenEventsToday => 'فعاليات اليوم';

  @override
  String get driverScreenFerries => 'العبّارات';

  @override
  String get driverScreenFetchingPosition => 'جارٍ تحديد الموقع…';

  @override
  String get driverScreenFilter => 'التصفية';

  @override
  String get driverScreenGpsOff => 'فعّل الموقع (GPS) في إعدادات الهاتف';

  @override
  String get driverScreenGpsTimeout =>
      'استغرق GPS وقتًا طويلًا — جرّب في الخارج أو أعد المحاولة';

  @override
  String get driverScreenGroupMedium => 'متوسطة';

  @override
  String get driverScreenGroupOther => 'أخرى';

  @override
  String get driverScreenGroupStrong => 'قوية';

  @override
  String driverScreenGroupTitle(String name, int count) {
    return '$name · $count';
  }

  @override
  String get driverScreenGroupWeak => 'ضعيفة';

  @override
  String driverScreenHidden(String types) {
    return 'مخفي: $types';
  }

  @override
  String driverScreenHiddenTiers(int count) {
    String _temp0 = intl.Intl.pluralLogic(
      count,
      locale: localeName,
      other: '$count نوع اضطراب مخفي',
      many: '$count نوع اضطراب مخفي',
      few: '$count أنواع اضطرابات مخفية',
      two: 'نوعا اضطراب مخفيان',
      one: 'نوع اضطراب واحد مخفي',
    );
    return '$_temp0';
  }

  @override
  String get driverScreenHistory => 'السجل';

  @override
  String driverScreenKm(int km) {
    return '$km كم';
  }

  @override
  String get driverScreenLegend => 'ماذا تعني الرموز؟';

  @override
  String get driverScreenLocationAllow =>
      'اسمح بالموقع لتطبيق TaxiTips في إعدادات الهاتف';

  @override
  String get driverScreenLocationDenied => 'تم رفض إذن الموقع';

  @override
  String get driverScreenLocationTimeout => 'استغرق تحديد الموقع وقتًا طويلًا';

  @override
  String driverScreenLockedCount(int count) {
    String _temp0 = intl.Intl.pluralLogic(
      count,
      locale: localeName,
      other: 'توجد حاليًا $count نصيحة من هذا النوع في منطقتك.',
      many: 'توجد حاليًا $count نصيحة من هذا النوع في منطقتك.',
      few: 'توجد حاليًا $count نصائح من هذا النوع في منطقتك.',
      two: 'توجد حاليًا نصيحتان من هذا النوع في منطقتك.',
      one: 'توجد حاليًا نصيحة واحدة من هذا النوع في منطقتك.',
    );
    return '$_temp0';
  }

  @override
  String get driverScreenLoginInvalid =>
      'تسجيل الدخول لا يعمل. سجّل الدخول مرة أخرى.';

  @override
  String get driverScreenMoreDates => 'تواريخ أخرى';

  @override
  String get driverScreenMoreOptions => 'خيارات أكثر: إخفاء الأنواع';

  @override
  String get driverScreenMovedBody =>
      'حسابك مستخدم الآن على هاتف آخر. سجّل الدخول هنا مرة أخرى إذا أردت العودة. يمكن تغيير الهاتف مرة واحدة في الشهر.';

  @override
  String get driverScreenMovedTitle => 'تم تسجيل الدخول على هاتف آخر';

  @override
  String driverScreenMunicipalitiesChosen(int count) {
    String _temp0 = intl.Intl.pluralLogic(
      count,
      locale: localeName,
      other: 'تم اختيار $count بلدية',
      many: 'تم اختيار $count بلدية',
      few: 'تم اختيار $count بلديات',
      two: 'تم اختيار بلديتين',
      one: 'تم اختيار بلدية واحدة',
    );
    return '$_temp0';
  }

  @override
  String get driverScreenMyPosition => 'موقعي';

  @override
  String get driverScreenNavFailed => 'تعذّر فتح الملاحة.';

  @override
  String get driverScreenNearMe => 'قربي';

  @override
  String get driverScreenNearYou => 'قربك';

  @override
  String get driverScreenNearYou25 => 'قربك (25 كم)';

  @override
  String get driverScreenNeedsInternet =>
      'يتطلب الإنترنت. حاول مرة أخرى عندما يتوفر لديك اتصال.';

  @override
  String get driverScreenNoAccess =>
      'ليس لهذا الهاتف صلاحية الوصول. سجّل الدخول مرة أخرى، أو اطلب من مديرك أن يدعوك.';

  @override
  String get driverScreenNoCountiesYet =>
      'لا توجد مقاطعات بعد. اختر سيارة أولًا.';

  @override
  String get driverScreenNoCounty => 'لم تُختر أي مقاطعة';

  @override
  String get driverScreenNoEventsDays => 'لا فعاليات في هذه الأيام.';

  @override
  String driverScreenNoEventsWithin(int km) {
    return 'لا فعاليات ضمن $km كم. اختر مسافة أطول.';
  }

  @override
  String get driverScreenNoFerries => 'لا توجد عبّارات قادمة الآن.';

  @override
  String driverScreenNoNewTips(String web) {
    return 'لا تظهر نصائح جديدة الآن. $web هذا لا يعني \"لا توجد اضطرابات الآن\".';
  }

  @override
  String get driverScreenNoRoadAccidents => 'لا حوادث سير في منطقتك الآن.';

  @override
  String get driverScreenNoTipsFilters => 'لا نصائح بهذه المرشحات.';

  @override
  String driverScreenNotUpdated(String time) {
    return 'لم يتم التحديث منذ $time';
  }

  @override
  String get driverScreenNothingSaved =>
      'لا شيء محفوظ بعد.\n\nاضغط ☆ على نصيحة أو فعالية. تُحفظ النصائح لمدة سبعة أيام، والفعاليات حتى اليوم التالي.';

  @override
  String get driverScreenNow => 'الآن';

  @override
  String get driverScreenOnlyStrong => 'القوية فقط';

  @override
  String get driverScreenOnlyStrongest => 'الأقوى فقط';

  @override
  String get driverScreenOpenSettings => 'افتح الإعدادات';

  @override
  String driverScreenPausedBody(String notice) {
    return '$notice هذا لا يعني \"لا توجد اضطرابات الآن\".';
  }

  @override
  String get driverScreenPausedTitle => 'العضوية متوقفة مؤقتًا';

  @override
  String get driverScreenPhonePaired => 'تم ربط الهاتف';

  @override
  String get driverScreenPositionFailed => 'تعذّر الحصول على موقعك';

  @override
  String get driverScreenPositionFailedShort => 'تعذّر الحصول على الموقع';

  @override
  String get driverScreenPresetAll => 'الكل';

  @override
  String get driverScreenPresetStrong => 'القوية';

  @override
  String get driverScreenPresetStrongest => 'الأقوى';

  @override
  String driverScreenRecentlyOver(int count) {
    return 'انتهت للتو ($count)';
  }

  @override
  String get driverScreenRemovedSnack => 'تمت الإزالة من المحفوظ.';

  @override
  String get driverScreenResetFilter => 'إعادة ضبط التصفية';

  @override
  String get driverScreenRoadOnly =>
      'حوادث السير فقط. أعمال الطرق والإغلاقات غير معروضة.';

  @override
  String get driverScreenSaveFailed => 'تعذّر حفظ النصيحة';

  @override
  String get driverScreenSaved => 'المحفوظ';

  @override
  String get driverScreenSavedSnack =>
      'تم الحفظ. تظهر ضمن ⭐ المحفوظ لمدة سبعة أيام.';

  @override
  String get driverScreenSectionTips => 'النصائح';

  @override
  String get driverScreenSeeSettings => 'انظر الإعدادات';

  @override
  String get driverScreenSettings => 'الإعدادات';

  @override
  String get driverScreenSettingsNewReply => 'الإعدادات – رد جديد من الدعم';

  @override
  String get driverScreenShow => 'عرض';

  @override
  String get driverScreenShowAll => 'عرض الكل';

  @override
  String get driverScreenShowDistance => 'عرض المسافة';

  @override
  String get driverScreenShowFullList => 'عرض القائمة كاملة';

  @override
  String get driverScreenShowMap => 'عرض الخريطة';

  @override
  String get driverScreenSort => 'ترتيب';

  @override
  String get driverScreenSortImportant => 'الأهم';

  @override
  String get driverScreenSortNearest => 'الأقرب';

  @override
  String get driverScreenSortNewest => 'الأحدث';

  @override
  String get driverScreenStrength => 'القوة';

  @override
  String driverScreenStrengthRange(int min, int max) {
    return 'القوة $min–$max';
  }

  @override
  String get driverScreenTipGone =>
      'النصيحة لم تعد موجودة، أو أن السيارة لا يمكنها الوصول إليها.';

  @override
  String get driverScreenTipsPausedTitle => 'النصائح متوقفة مؤقتًا';

  @override
  String get driverScreenTrialEndedTitle => 'انتهت الفترة التجريبية';

  @override
  String get driverScreenTrialNotStartedBody =>
      'اختر المقاطعات من الإعدادات. تتم دعوة السائقين عبر الموقع. تبدأ الفترة التجريبية عندما يسجّل أول سائق دخوله.';

  @override
  String get driverScreenTrialNotStartedTitle => 'مرحبًا! خطوة واحدة متبقية';

  @override
  String get driverScreenUnsaveFailed => 'تعذّرت إزالة النصيحة';

  @override
  String get driverScreenWholeCounty => 'المقاطعة كاملة · اختر البلديات';

  @override
  String get driverScreenWholeCountyShort => 'المقاطعة كاملة';

  @override
  String get driverScreenWithin25 => 'ضمن حوالي 25 كم';

  @override
  String get driverScreenYellowShown => 'الأصفر = معروض. اضغط للإخفاء.';

  @override
  String get driverScreenZoomIn => 'تكبير';

  @override
  String get driverScreenZoomOut => 'تصغير';

  @override
  String get driverTourCategoriesText =>
      'اختر ما تريد رؤيته: قطار وحافلة، طريق، طيران، عبّارة أو فعاليات. الرقم هو عدد النصائح. \"المحفوظ\" يعرض النصائح التي حفظتها.';

  @override
  String get driverTourCategoriesTitle => 'الفئات';

  @override
  String get driverTourDrive => 'اذهب إلى هناك';

  @override
  String get driverTourFilterText =>
      'من التصفية تختار المقاطعة وقوة النصائح التي تريد رؤيتها وما يجب إخفاؤه. اختر مقاطعتك هنا لتصلك النصائح منها.';

  @override
  String get driverTourFilterTitle => 'التصفية والمقاطعة';

  @override
  String get driverTourHowWasIt => 'كيف سارت الأمور؟';

  @override
  String get driverTourListText =>
      'هذه هي النصائح القريبة منك. الأقوى في الأعلى. اسحب القائمة لأعلى لرؤية المزيد.';

  @override
  String get driverTourListTitle => 'قائمة النصائح';

  @override
  String get driverTourMapText =>
      'كل دبوس هو نصيحة، ولونه مثل لون النصيحة. اضغط على دبوس لفتح النصيحة. في الأعلى تشرح علامة الاستفهام الرموز، وأيقونة الساعة في الزاوية هي السجل: نصائح آخر 24 ساعة.';

  @override
  String get driverTourMapTitle => 'الخريطة والدبابيس';

  @override
  String get driverTourSave => 'حفظ';

  @override
  String get driverTourSettingsDriver =>
      'هنا تفعّل الإشعارات وتختار السيارة التي تقودها. تنبّهك الإشعارات عند ظهور نصيحة قوية قربك. الجولة تبقى متاحة ضمن المساعدة.';

  @override
  String get driverTourSettingsOwner =>
      'هنا تختار المقاطعة وتفعّل الإشعارات. تتم دعوة السائقين عبر الموقع. وهنا تختار أيضًا المكان الذي تعمل به. الجولة تبقى متاحة ضمن المساعدة.';

  @override
  String get driverTourSettingsTitle => 'الإعدادات';

  @override
  String get driverTourStrengthText =>
      'لكل نصيحة لون وكلمة. في أسفل القائمة يوجد \"أخرى\": رسائل من شركات النقل. هذه معلومات وليست نصائح.';

  @override
  String get driverTourStrengthTitle => 'اللون يدل على القوة';

  @override
  String get driverTourTipText =>
      'تفتح ورقة فيها المزيد عن النصيحة. يمكنك هناك الذهاب إلى المكان وحفظ النصيحة والإجابة عن كيف سارت الأمور. إجاباتك تجعل النصائح أفضل.';

  @override
  String get driverTourTipTitle => 'اضغط على نصيحة';

  @override
  String get eventsScreenAllCounties => 'كل المقاطعات';

  @override
  String get eventsScreenAllKinds => 'كل الأنواع';

  @override
  String eventsScreenCount(int count) {
    String _temp0 = intl.Intl.pluralLogic(
      count,
      locale: localeName,
      other: '$count فعالية',
      many: '$count فعالية',
      few: '$count فعاليات',
      two: 'فعاليتان',
      one: 'فعالية واحدة',
      zero: 'لا فعاليات',
    );
    return '$_temp0';
  }

  @override
  String eventsScreenError(String error) {
    return 'تعذّر تحميل الفعاليات: $error';
  }

  @override
  String get eventsScreenFollowing =>
      'أنت تتابع الفعالية. ستجدها تحت ⭐ المحفوظات على الخريطة.';

  @override
  String eventsScreenLoading(String period) {
    return 'جارٍ تحميل $period…';
  }

  @override
  String get eventsScreenMonth => '30 يوماً';

  @override
  String eventsScreenNone(String period) {
    return 'لا توجد فعاليات $period في منطقتك.';
  }

  @override
  String get eventsScreenNoneHint =>
      'الأيام أعلاه فيها فعاليات — اضغط على أحدها، أو اختر فترة أطول.';

  @override
  String get eventsScreenNoneThin =>
      'عدد الفعاليات قليل خارج المدن الكبرى. جرّب مقاطعة أخرى.';

  @override
  String get eventsScreenOtherKind => 'أخرى';

  @override
  String get eventsScreenPickDay => 'اختر يوماً';

  @override
  String get eventsScreenPickPeriod => 'اختر فترة';

  @override
  String get eventsScreenQuarter => '3 أشهر';

  @override
  String get eventsScreenSortLargest => 'الأكبر';

  @override
  String get eventsScreenSortNearest => 'الأقرب';

  @override
  String get eventsScreenSortTime => 'الوقت';

  @override
  String eventsScreenSummary(String count, String period) {
    return '$count · $period';
  }

  @override
  String eventsScreenSummaryFiltered(int shown, int total, String period) {
    return '$shown من أصل $total فعالية · $period';
  }

  @override
  String get eventsScreenTitle => 'الفعاليات';

  @override
  String get eventsScreenToday => 'اليوم';

  @override
  String get eventsScreenTodayPrefix => 'اليوم · ';

  @override
  String get eventsScreenTomorrow => 'غداً';

  @override
  String get eventsScreenTomorrowPrefix => 'غداً · ';

  @override
  String get eventsScreenUnfollowed => 'لم تعد تتابعها.';

  @override
  String get eventsScreenWeek => '7 أيام';

  @override
  String get eventsScreenWeekend => 'عطلة نهاية الأسبوع';

  @override
  String get eventsScreenWholeArea => 'المنطقة كلها';

  @override
  String get ferryEventApproaching => 'في الطريق إلى الميناء';

  @override
  String get ferryEventAtQuay => 'عند الرصيف';

  @override
  String ferryEventAtQuaySince(String clock) {
    return 'عند الرصيف منذ $clock';
  }

  @override
  String ferryEventAtTime(String time) {
    return 'الساعة $time';
  }

  @override
  String get ferryEventByTimetable => 'حسب الجدول';

  @override
  String get ferryEventConfirmed => 'مؤكدة';

  @override
  String get ferryEventConfirmedApproaching =>
      'مؤكدة – السفينة في الطريق إلى الميناء';

  @override
  String get ferryEventConfirmedBerthed => 'مؤكدة – السفينة عند الرصيف';

  @override
  String ferryEventDistance(String distance, String time) {
    return '$distance · نحو $time بالسيارة';
  }

  @override
  String get ferryEventDockingNow => 'ترسو الآن';

  @override
  String ferryEventDocksAt(String clock, String relative) {
    return 'ترسو $clock · $relative';
  }

  @override
  String ferryEventEarly(String time) {
    return 'مبكرة $time';
  }

  @override
  String get ferryEventEndEstimated => 'وقت الانتهاء تقديري وليس من المنظّم.';

  @override
  String ferryEventEndsAbout(String time) {
    return 'تنتهي نحو $time';
  }

  @override
  String get ferryEventFerry => 'عبّارة';

  @override
  String get ferryEventFollow => 'تابع';

  @override
  String get ferryEventFollowing => 'تتابع';

  @override
  String ferryEventFrom(String place) {
    return 'من $place';
  }

  @override
  String get ferryEventInternational => 'دولي';

  @override
  String ferryEventLate(String time) {
    return 'متأخرة $time';
  }

  @override
  String get ferryEventOnTime => 'في الموعد';

  @override
  String get ferryEventOngoing => 'جارية الآن';

  @override
  String ferryEventOriginDeparted(String from, String clock) {
    return '$from، غادرت $clock';
  }

  @override
  String ferryEventOriginDeparts(String from, String clock) {
    return '$from، تغادر $clock';
  }

  @override
  String ferryEventPeopleLeave(String time) {
    return 'الناس يغادرون حتى $time';
  }

  @override
  String ferryEventPickupNow(String clock) {
    return 'الناس يخرجون الآن، حتى $clock';
  }

  @override
  String ferryEventPickupRange(String range) {
    return 'الناس يخرجون $range';
  }

  @override
  String ferryEventPickupValueNow(String clock) {
    return 'الآن، حتى $clock';
  }

  @override
  String ferryEventReachAfter(String clock) {
    return 'الوصول نحو $clock – بعد أن غادر معظمهم';
  }

  @override
  String ferryEventReachBefore(String clock) {
    return 'الوصول نحو $clock – قبل خروج الناس';
  }

  @override
  String ferryEventReachDuring(String clock) {
    return 'الوصول نحو $clock – أثناء خروج الناس';
  }

  @override
  String ferryEventReachNoWindow(String clock) {
    return 'الوصول نحو $clock';
  }

  @override
  String get ferryEventRowArrival => 'الوصول';

  @override
  String get ferryEventRowAtQuay => 'عند الرصيف';

  @override
  String get ferryEventRowCertainty => 'مدى التأكد';

  @override
  String get ferryEventRowComingFrom => 'قادمة من';

  @override
  String get ferryEventRowDelay => 'التأخير';

  @override
  String get ferryEventRowDistance => 'المسافة';

  @override
  String get ferryEventRowEndsAbout => 'تنتهي نحو';

  @override
  String get ferryEventRowKind => 'النوع';

  @override
  String get ferryEventRowOperator => 'شركة الشحن';

  @override
  String get ferryEventRowPeopleCome => 'خروج الناس';

  @override
  String get ferryEventRowPeopleLeaving => 'خروج الناس';

  @override
  String get ferryEventRowQuay => 'الرصيف';

  @override
  String get ferryEventRowReach => 'هل ستصل في الوقت';

  @override
  String get ferryEventRowRoute => 'الخط';

  @override
  String get ferryEventRowSameQuay => 'نفس الرصيف ±30 دقيقة';

  @override
  String get ferryEventRowService => 'نوع الخدمة';

  @override
  String get ferryEventRowSize => 'الحجم';

  @override
  String get ferryEventRowStatus => 'الحالة';

  @override
  String get ferryEventRowTimetable => 'الجدول';

  @override
  String ferryEventSameMany(int count) {
    String _temp0 = intl.Intl.pluralLogic(
      count,
      locale: localeName,
      other: '$count عبّارة أخرى تصل',
      many: '$count عبّارة أخرى تصل',
      few: '$count عبّارات أخرى تصل',
      two: 'عبّارتان أخريان تصلان',
      one: 'عبّارة أخرى تصل',
      zero: 'لا عبّارات أخرى تصل',
    );
    return '$_temp0';
  }

  @override
  String ferryEventSameManyFirst(int count, String at) {
    String _temp0 = intl.Intl.pluralLogic(
      count,
      locale: localeName,
      other: '$count عبّارة أخرى تصل، الأولى $at',
      many: '$count عبّارة أخرى تصل، الأولى $at',
      few: '$count عبّارات أخرى تصل، الأولى $at',
      two: 'عبّارتان أخريان تصلان، الأولى $at',
      one: 'عبّارة أخرى تصل $at',
      zero: 'لا عبّارات أخرى تصل',
    );
    return '$_temp0';
  }

  @override
  String get ferryEventSameOne => 'عبّارة أخرى تصل';

  @override
  String ferryEventSameOneAt(String at) {
    return 'عبّارة أخرى تصل $at';
  }

  @override
  String get ferryEventSectionContext => 'السياق';

  @override
  String get ferryEventSectionWhen => 'متى';

  @override
  String get ferryEventSectionWhere => 'أين';

  @override
  String get ferryEventSectionWho => 'من ينزل';

  @override
  String ferryEventShouldHaveDocked(String clock) {
    return 'كان من المقرر أن ترسو $clock حسب الجدول';
  }

  @override
  String get ferryEventSizeLarge => 'عبّارة كبيرة';

  @override
  String get ferryEventSizeMedium => 'عبّارة متوسطة';

  @override
  String get ferryEventSizeSmall => 'عبّارة صغيرة';

  @override
  String get ferryEventTimeNotSet => 'الوقت غير محدد';

  @override
  String get ferryEventToday => 'اليوم';

  @override
  String get ferryEventTomorrow => 'غداً';

  @override
  String get ferryEventUnknown => 'غير معروف';

  @override
  String ferryEventVenueCapacity(String capacity) {
    return 'سعة الملعب $capacity';
  }

  @override
  String ferryEventVenueCapacityNote(String capacity) {
    return 'سعة الملعب $capacity (السعة وليس عدد الحضور)';
  }

  @override
  String get followUpCardClose => 'إغلاق';

  @override
  String followUpCardDrove(String place, String time) {
    return 'قدت نحو $place $time';
  }

  @override
  String get forceUpgradeBody =>
      'هذا الإصدار لم يعد يعمل. حدّث التطبيق للمتابعة.';

  @override
  String get forceUpgradeClose => 'إغلاق';

  @override
  String get forceUpgradeNudge => 'يتوفر إصدار جديد. حدّث عندما تستطيع.';

  @override
  String get forceUpgradeTitle => 'حدّث التطبيق';

  @override
  String get forceUpgradeUpdate => 'تحديث';

  @override
  String forceUpgradeVersions(String installed, String required) {
    return 'إصدارك: $installed  ·  المطلوب: $required';
  }

  @override
  String get guidedTourDone => 'تم';

  @override
  String get guidedTourNext => 'التالي';

  @override
  String get guidedTourSkip => 'تخطَّ';

  @override
  String guidedTourStep(int position, int total) {
    return 'الخطوة $position من $total';
  }

  @override
  String get historyScreenAnd => ' و ';

  @override
  String get historyScreenEarlier => 'بدأت قبل ذلك';

  @override
  String get historyScreenEnded => 'انتهى';

  @override
  String historyScreenHidden(int count) {
    return '$count نصائح غير معروضة.';
  }

  @override
  String historyScreenHiddenIn(int count, String categories) {
    return '$count نصائح في $categories غير معروضة.';
  }

  @override
  String historyScreenHours(int hours) {
    return '$hours س';
  }

  @override
  String get historyScreenLoadError => 'تعذّر تحميل السجل. حاول مرة أخرى.';

  @override
  String get historyScreenNeedsArea => 'اختر منطقة قيادتك لعرض السجل.';

  @override
  String get historyScreenNoAccess =>
      'يظهر السجل عندما يكون للهاتف حق الوصول إلى النصائح.';

  @override
  String historyScreenNone(int hours) {
    return 'لا نصائح في آخر $hours ساعة.';
  }

  @override
  String get historyScreenOngoing => 'جارٍ';

  @override
  String get historyScreenRetry => 'حاول مرة أخرى';

  @override
  String historyScreenShowingLatest(int count) {
    return 'عرض آخر $count.';
  }

  @override
  String historyScreenSummary(int count, int hours, int active) {
    return '$count نصيحة في آخر $hours ساعة · $active جارية';
  }

  @override
  String get historyScreenTitle => 'السجل';

  @override
  String get historyScreenUnavailable => 'السجل غير متوفر في هذا الإصدار.';

  @override
  String get languageButtonLabel => 'تغيير اللغة';

  @override
  String languageCurrentAuto(String language) {
    return '$language (لغة الهاتف)';
  }

  @override
  String get languageFollowPhone => 'لغة الهاتف';

  @override
  String languageFollowPhoneDetail(String language) {
    return 'الآن: $language';
  }

  @override
  String get languageSectionDescription =>
      'يتبع التطبيق لغة هاتفك إذا كانت متوفرة.';

  @override
  String get languageTitle => 'اللغة';

  @override
  String get netStatusGenericError => 'حدث خطأ ما. حاول مرة أخرى.';

  @override
  String get netStatusOffline => 'لا يوجد اتصال بالإنترنت';

  @override
  String get netStatusTimeout => 'الاتصال ضعيف. حاول مرة أخرى.';

  @override
  String get netStatusUnreachable => 'الخادم لا يستجيب الآن';

  @override
  String get notificationLogSheetArchived => '· مؤرشف';

  @override
  String get notificationLogSheetEmptyBody =>
      'تُرسل الإشعارات فقط للاضطرابات التي تستحق مقاطعتك. إذا كان الوضع هادئًا في مقاطعاتك فلن يصلك شيء — وهذا مقصود.';

  @override
  String get notificationLogSheetEmptyTitle => 'لا توجد إشعارات بعد';

  @override
  String notificationLogSheetHoursAgo(int hours) {
    return 'قبل $hours ساعة';
  }

  @override
  String get notificationLogSheetIntro =>
      'الإشعارات التي أُرسلت إلى هذا الهاتف. تريد حفظ نصيحة؟ استخدم النجمة في قائمة النصائح — ثم تبقى ضمن المحفوظ لمدة سبعة أيام.';

  @override
  String notificationLogSheetMinAgo(int minutes) {
    return 'قبل $minutes دقيقة';
  }

  @override
  String get notificationLogSheetNeedsBackend => 'سجل الإشعارات يتطلب الخادم';

  @override
  String get notificationLogSheetNoPhone => 'لا يوجد هاتف مقترن';

  @override
  String get notificationLogSheetNoPhoneBody =>
      'تُرسل الإشعارات إلى جهاز مقترن. هذا الحساب ليس لديه جهاز.';

  @override
  String get notificationLogSheetNow => 'الآن';

  @override
  String get notificationLogSheetTitle => 'إشعاراتي';

  @override
  String notifyPrefsAreaLine(String counties) {
    return 'منطقة العمل: $counties';
  }

  @override
  String get notifyPrefsByArea => 'حسب منطقة العمل';

  @override
  String get notifyPrefsHowImportant => 'ما درجة الأهمية؟';

  @override
  String get notifyPrefsLevelAll => 'الكل';

  @override
  String get notifyPrefsLevelMedium => 'متوسطة +';

  @override
  String get notifyPrefsLevelStrong => 'قوية';

  @override
  String get notifyPrefsMoreOptions => 'خيارات إضافية';

  @override
  String get notifyPrefsNeedsLocation =>
      'وضع الخدمة يحتاج إلى الموقع أثناء استخدام التطبيق';

  @override
  String get notifyPrefsNoActiveSeat =>
      'لا يوجد مقعد نشط على هذا الجهاز — لا يمكن حفظ الإعدادات.';

  @override
  String get notifyPrefsOnAgain => 'الإشعارات تعمل مرة أخرى.';

  @override
  String get notifyPrefsOnDuty => 'في الخدمة';

  @override
  String get notifyPrefsPause => 'إيقاف مؤقت';

  @override
  String get notifyPrefsPause1h => 'ساعة';

  @override
  String get notifyPrefsPause4h => '4 ساعات';

  @override
  String get notifyPrefsPauseTonight => 'الليلة';

  @override
  String notifyPrefsPausedUntilSnack(String time) {
    return 'متوقفة مؤقتًا حتى $time.';
  }

  @override
  String notifyPrefsPausedUntilTitle(String time) {
    return 'متوقفة مؤقتًا حتى $time';
  }

  @override
  String get notifyPrefsResume => 'تشغيل مرة أخرى';

  @override
  String get notifyPrefsSaved => 'تم الحفظ';

  @override
  String get notifyPrefsSendNotifications => 'إرسال الإشعارات';

  @override
  String get notifyPrefsTitle => 'الإشعارات';

  @override
  String notifyPrefsTomorrowAt(String time) {
    return 'غدًا $time';
  }

  @override
  String get notifyPrefsWhichNotifications => 'أي إشعارات؟';

  @override
  String get notifyPrefsWithinKm => 'ضمن 30 كم منك';

  @override
  String get notifyRulesApiInvalidResponse => 'رد غير صالح من الخادم';

  @override
  String notifyRulesApiServerResponded(int status) {
    return 'ردّ الخادم برمز $status';
  }

  @override
  String offlineBannerOffline(String at) {
    return 'غير متصل – عرض آخر النصائح من $at';
  }

  @override
  String get offlineBannerRetry => 'حاول مرة أخرى';

  @override
  String offlineBannerTimeout(String at) {
    return 'الاتصال ضعيف – عرض النصائح من $at';
  }

  @override
  String offlineBannerUnreachable(String at) {
    return 'الخادم لا يستجيب – عرض النصائح من $at';
  }

  @override
  String get settingsScreenAboutTips => 'حول التنبيهات';

  @override
  String get settingsScreenAccountClosed => 'تم إنهاء الحساب.';

  @override
  String get settingsScreenAccountDescription =>
      'سجّل الخروج إذا توقفت عن القيادة أو غيّرت هاتفك.';

  @override
  String get settingsScreenAccountTitle => 'الحساب';

  @override
  String get settingsScreenCancel => 'إلغاء';

  @override
  String get settingsScreenCloseAccountBody =>
      'لن يتم تجديد العضوية. وإذا كانت هناك فترة تجريبية فستنتهي. يمكنكم استخدام التطبيق حتى نهاية الفترة.';

  @override
  String get settingsScreenCloseAccountConfirm => 'إنهاء';

  @override
  String get settingsScreenCloseAccountTitle => 'إنهاء حساب الشركة؟';

  @override
  String get settingsScreenCloseCompanyAccount => 'إنهاء حساب الشركة';

  @override
  String get settingsScreenCompanyDescription =>
      'أدِر حساب الشركة من بوابة العملاء على الويب.';

  @override
  String get settingsScreenCompanyTitle => 'الشركة';

  @override
  String get settingsScreenCountiesMany =>
      'التنبيهات والإشعارات في مقاطعاتك. اضغط لاختيار المقاطعات.';

  @override
  String get settingsScreenCountiesOne =>
      'التنبيهات والإشعارات في هذه المقاطعة.';

  @override
  String get settingsScreenDelete => 'حذف';

  @override
  String get settingsScreenDeleteBodyDriver =>
      'سيُحذف حساب السائق الخاص بك ويُفصل الجهاز عن مقعدك. يمكن لمديرك دعوتك مرة أخرى. لا يمكن التراجع عن ذلك.';

  @override
  String get settingsScreenDeleteBodyOffice =>
      'سيُحذف حسابك وتسجيل دخولك نهائيًا. وستُفصل الأجهزة التي استخدمتها عن العضوية.\n\nإذا كنت المالك الوحيد، تُغلق الشركة فورًا: تنتهي العضوية وأي فترة تجريبية جارية، ويتوقف السائقون عن تلقي التنبيهات، وتُؤرشف الشركة. لا يمكن التراجع عن ذلك.';

  @override
  String get settingsScreenDeleteFailedTitle => 'لم يُحذف الحساب';

  @override
  String get settingsScreenDeleteMyAccount => 'حذف حسابي';

  @override
  String get settingsScreenDeleteTitle => 'حذف حسابك؟';

  @override
  String get settingsScreenDeleted => 'تم حذف حسابك.';

  @override
  String get settingsScreenHelpChat => 'تحدث معنا';

  @override
  String get settingsScreenHelpDescription =>
      'تعرّف على طريقة عمل التطبيق، أو راسلنا.';

  @override
  String get settingsScreenHelpHowDriver => 'أربع صفحات قصيرة';

  @override
  String get settingsScreenHelpHowItWorks => 'كيف يعمل Taxi Tips';

  @override
  String get settingsScreenHelpHowOffice =>
      'الفترة التجريبية والعضوية والسائقون';

  @override
  String get settingsScreenHelpTitle => 'المساعدة';

  @override
  String get settingsScreenHelpTour => 'عرض الجولة التعريفية مرة أخرى';

  @override
  String get settingsScreenHelpTourSub => 'تُظهر أين تضغط في الشاشة الرئيسية';

  @override
  String settingsScreenHelpUnread(int count) {
    String _temp0 = intl.Intl.pluralLogic(
      count,
      locale: localeName,
      other: '$count رد جديد',
      many: '$count ردًا جديدًا',
      few: '$count ردود جديدة',
      two: 'ردّان جديدان',
      one: 'رد جديد واحد',
      zero: 'لا ردود جديدة',
    );
    return '$_temp0';
  }

  @override
  String get settingsScreenLoginForSettings => 'سجّل الدخول لعرض الإعدادات.';

  @override
  String get settingsScreenLogout => 'تسجيل الخروج';

  @override
  String get settingsScreenMembershipDescription =>
      'المقعد الذي تعمل به والمقاطعات التي تصلك منها التنبيهات.';

  @override
  String settingsScreenMembershipDescriptionCompany(String company) {
    return 'المقعد الذي تعمل به والمقاطعات التي تصلك منها التنبيهات. الشركة: $company.';
  }

  @override
  String get settingsScreenMembershipTitle => 'العضوية';

  @override
  String get settingsScreenNotifyAllCounties => 'كل مقاطعاتك';

  @override
  String get settingsScreenNotifyDescription =>
      'اختر متى ينبّهك الهاتف إلى تنبيه قوي.';

  @override
  String settingsScreenNotifyFilter(String counties) {
    return 'التصفية: $counties';
  }

  @override
  String get settingsScreenNotifyTitle => 'الإشعارات';

  @override
  String get settingsScreenOk => 'حسنًا';

  @override
  String get settingsScreenPrivacy => 'سياسة البيانات';

  @override
  String get settingsScreenSignedInAs => 'مسجَّل الدخول باسم';

  @override
  String get settingsScreenTerms => 'الشروط';

  @override
  String get settingsScreenTitle => 'الإعدادات';

  @override
  String get settingsScreenYourCounties => 'مقاطعاتك';

  @override
  String severityLabelsCancelledAt(String clock) {
    return 'ملغاة $clock';
  }

  @override
  String severityLabelsClockChange(String from, String to) {
    return '$from ← $to';
  }

  @override
  String get severityLabelsCompensationBase =>
      'يمكن للمسافر الحصول على تعويض عن التاكسي';

  @override
  String get severityLabelsCompensationMaybe => 'قد يُعوَّض التاكسي';

  @override
  String severityLabelsCompensationSentenceUpTo(String amount, String per) {
    String _temp0 = intl.Intl.selectLogic(per, {
      'person': ' لكل مسافر',
      'trip': ' لكل رحلة',
      'other': '',
    });
    return 'يمكن للمسافر الحصول على تعويض عن التاكسي حتى $amount kr$_temp0';
  }

  @override
  String severityLabelsCompensationUpTo(int amount, String per) {
    String _temp0 = intl.Intl.selectLogic(per, {
      'person': ' لكل مسافر',
      'trip': ' لكل رحلة',
      'other': '',
    });
    return 'يُعوَّض التاكسي · حتى $amount kr$_temp0';
  }

  @override
  String get severityLabelsConfidenceHigh => 'عالية — واضحة في بيانات المصدر';

  @override
  String get severityLabelsConfidenceLow =>
      'منخفضة — قراءة غير مؤكدة لبيانات المصدر';

  @override
  String get severityLabelsConfidenceMedium => 'متوسطة';

  @override
  String get severityLabelsDelayed => 'متأخرة';

  @override
  String severityLabelsDelayedBy(String delay) {
    return 'متأخرة $delay';
  }

  @override
  String get severityLabelsDeparted => 'غادرت';

  @override
  String get severityLabelsDepartsNow => 'تغادر الآن';

  @override
  String severityLabelsHours(int hours) {
    return '$hours س';
  }

  @override
  String severityLabelsHoursMinutes(int hours, int minutes) {
    return '$hours س $minutes د';
  }

  @override
  String severityLabelsIn(String time) {
    return 'بعد $time';
  }

  @override
  String severityLabelsMinutes(int minutes) {
    return '$minutes د';
  }

  @override
  String get severityLabelsModeBoat => 'قارب';

  @override
  String get severityLabelsModeBus => 'حافلة';

  @override
  String get severityLabelsModeEvents => 'فعاليات';

  @override
  String get severityLabelsModeFerries => 'عبّارات';

  @override
  String get severityLabelsModeFlight => 'طيران';

  @override
  String get severityLabelsModeMetro => 'مترو';

  @override
  String get severityLabelsModeRoad => 'طريق';

  @override
  String get severityLabelsModeTrain => 'قطار';

  @override
  String get severityLabelsModeTram => 'ترام';

  @override
  String severityLabelsMonthShort(String m) {
    String _temp0 = intl.Intl.selectLogic(m, {
      'm1': 'يناير',
      'm2': 'فبراير',
      'm3': 'مارس',
      'm4': 'أبريل',
      'm5': 'مايو',
      'm6': 'يونيو',
      'm7': 'يوليو',
      'm8': 'أغسطس',
      'm9': 'سبتمبر',
      'm10': 'أكتوبر',
      'm11': 'نوفمبر',
      'm12': 'ديسمبر',
      'other': '',
    });
    return '$_temp0';
  }

  @override
  String get severityLabelsShortArrivalWave => 'موجة وصول';

  @override
  String get severityLabelsShortIgnore => 'أخرى';

  @override
  String get severityLabelsShortLastArrival => 'آخر وصول';

  @override
  String get severityLabelsShortLineDelayed => 'تأخير، والخط يعمل';

  @override
  String get severityLabelsShortLinePaused => 'الخط كله متوقف';

  @override
  String get severityLabelsShortRoadAccident => 'حادث/إغلاق';

  @override
  String get severityLabelsShortRoadWork => 'أعمال طريق';

  @override
  String get severityLabelsShortRoadWorkQueue => 'أعمال طريق/ازدحام';

  @override
  String get severityLabelsShortUnclassified => 'تقدير غير مؤكد';

  @override
  String get severityLabelsShortVehicleCancelled => 'رحلة واحدة ملغاة';

  @override
  String get severityLabelsShortVehicleDelayed => 'رحلة واحدة متأخرة';

  @override
  String get severityLabelsTierArrivalWave => 'طائرات كثيرة تهبط في وقت واحد';

  @override
  String get severityLabelsTierArrivalWaveFerry =>
      'عبّارات كثيرة تصل في وقت واحد';

  @override
  String get severityLabelsTierIgnore => 'أخرى – رسالة من شركة النقل';

  @override
  String get severityLabelsTierLastArrival =>
      'آخر طائرة — لن تهبط طائرات أخرى لعدة ساعات';

  @override
  String get severityLabelsTierLastArrivalFerry =>
      'آخر عبّارة — لن تصل عبّارات أخرى لعدة ساعات';

  @override
  String get severityLabelsTierLineDelayed => 'تأخير على الخط';

  @override
  String get severityLabelsTierLinePaused => 'الخط كله متوقف';

  @override
  String get severityLabelsTierRoadAccident => 'حادث أو طريق مغلق';

  @override
  String get severityLabelsTierRoadWork => 'أعمال طريق صغيرة';

  @override
  String get severityLabelsTierRoadWorkQueue => 'أعمال طريق أو ازدحام';

  @override
  String get severityLabelsTierUnclassified => 'اضطراب (تصنيف غير مؤكد)';

  @override
  String get severityLabelsTierVehicleCancelled => 'رحلة واحدة أُلغيت';

  @override
  String get severityLabelsTierVehicleDelayed => 'رحلة واحدة متأخرة';

  @override
  String get severityLabelsTipFallback => 'تنبيه';

  @override
  String severityLabelsTitleWithMode(String mode, String title) {
    return '$mode: $title';
  }

  @override
  String severityLabelsTowards(String destination) {
    return 'باتجاه $destination';
  }

  @override
  String get severityLabelsWaitLast => 'آخر رحلة من هنا';

  @override
  String severityLabelsWaitThere(String at, String gap) {
    return 'التالية إلى هناك$at، بعد $gap';
  }

  @override
  String severityLabelsWaitThereFirst(String at, String gap) {
    return 'التالية إلى هناك فقط$at، بعد $gap';
  }

  @override
  String severityLabelsWaitTrip(String at, String gap) {
    return 'الرحلة التالية$at، بعد $gap';
  }

  @override
  String severityLabelsWaitTripFirst(String at, String gap) {
    return 'الرحلة التالية فقط$at، بعد $gap';
  }

  @override
  String get signalCardDrive => 'اذهب إلى هناك';

  @override
  String get signalCardNoteBody =>
      'نقرأ حركة المرور ونعرض أين قد يحتاج الناس إلى سيارة أجرة. أنت تقرر إن كان الذهاب يستحق.';

  @override
  String get signalCardNoteLine =>
      'نصائح من وضع حركة المرور، دون ضمان لوجود رحلة';

  @override
  String signalCardNoteMore(String title) {
    return '$title. عرض المزيد';
  }

  @override
  String get signalCardNoteOk => 'فهمت';

  @override
  String get signalCardNoteTitle => 'نصائح وليست طلبات';

  @override
  String get signalCardOver => 'انتهى';

  @override
  String get signalCardSave => 'احفظ النصيحة';

  @override
  String get signalCardTaxiPays => 'سيارة الأجرة مدفوعة';

  @override
  String get signalCardUnsave => 'إزالة من المحفوظ';

  @override
  String signalKindsAgoDays(int days) {
    return '$days يوم';
  }

  @override
  String get signalKindsAgoNow => 'الآن';

  @override
  String get signalKindsCategoryEvent => 'فعالية';

  @override
  String get signalKindsCategoryFerry => 'عبّارة';

  @override
  String get signalKindsCategoryFlight => 'طيران';

  @override
  String get signalKindsCategoryRoad => 'طريق';

  @override
  String get signalKindsCategoryTransit => 'قطار وحافلة';

  @override
  String signalKindsDistanceKm(String km) {
    return '$km كم';
  }

  @override
  String signalKindsDistanceMeters(int meters) {
    return '$meters م';
  }

  @override
  String get signalKindsExplainEvent =>
      'مباراة أو حفلة أو غيرها. الجمهور يعود إلى منازله في وقت واحد.';

  @override
  String get signalKindsExplainFerry =>
      'عبّارة في طريقها إلى الميناء. الركاب ينزلون في الميناء.';

  @override
  String get signalKindsExplainFlight =>
      'طائرات كثيرة تهبط، أو آخر رحلة. الناس يحتاجون إلى تاكسي من المطار.';

  @override
  String get signalKindsExplainRoad =>
      'حادث مروري. توقع ازدحاماً، أو اسلك طريقاً آخر.';

  @override
  String get signalKindsExplainTransit =>
      'القطار أو الحافلة أو المترو متوقف أو متأخر. الناس يحتاجون إلى تاكسي.';

  @override
  String signalKindsLongDayRelative(String relative, String weekday) {
    return '$relative، $weekday';
  }

  @override
  String get signalKindsMeaningHigh =>
      'من المرجح أن الناس يحتاجون إلى تاكسي هنا.';

  @override
  String get signalKindsMeaningLow => 'على الأرجح قلة يحتاجون إلى تاكسي هنا.';

  @override
  String get signalKindsMeaningMedium => 'قد يستحق المتابعة. ابقَ منتبهاً.';

  @override
  String signalKindsMonthLong(String m) {
    String _temp0 = intl.Intl.selectLogic(m, {
      'm1': 'يناير',
      'm2': 'فبراير',
      'm3': 'مارس',
      'm4': 'أبريل',
      'm5': 'مايو',
      'm6': 'يونيو',
      'm7': 'يوليو',
      'm8': 'أغسطس',
      'm9': 'سبتمبر',
      'm10': 'أكتوبر',
      'm11': 'نوفمبر',
      'm12': 'ديسمبر',
      'other': '',
    });
    return '$_temp0';
  }

  @override
  String get signalKindsRoadClosed => 'الطريق مغلق';

  @override
  String get signalKindsRoadHazard => 'عائق على الطريق';

  @override
  String get signalKindsRoadMajor => 'اضطراب كبير';

  @override
  String get signalKindsToday => 'اليوم';

  @override
  String get signalKindsTomorrow => 'غداً';

  @override
  String signalKindsWeekdayLong(String d) {
    String _temp0 = intl.Intl.selectLogic(d, {
      'd1': 'الإثنين',
      'd2': 'الثلاثاء',
      'd3': 'الأربعاء',
      'd4': 'الخميس',
      'd5': 'الجمعة',
      'd6': 'السبت',
      'd7': 'الأحد',
      'other': '',
    });
    return '$_temp0';
  }

  @override
  String signalKindsWeekdayShort(String d) {
    String _temp0 = intl.Intl.selectLogic(d, {
      'd1': 'الإثنين',
      'd2': 'الثلاثاء',
      'd3': 'الأربعاء',
      'd4': 'الخميس',
      'd5': 'الجمعة',
      'd6': 'السبت',
      'd7': 'الأحد',
      'other': '',
    });
    return '$_temp0';
  }

  @override
  String get signalKindsWordAccident => 'حادث';

  @override
  String get signalKindsWordBig => 'كبيرة';

  @override
  String get signalKindsWordMedium => 'متوسطة';

  @override
  String get signalKindsWordMiddle => 'متوسطة';

  @override
  String get signalKindsWordQueue => 'ازدحام';

  @override
  String get signalKindsWordSmall => 'صغيرة';

  @override
  String get signalKindsWordStrong => 'قوية';

  @override
  String get signalKindsWordWeak => 'ضعيفة';

  @override
  String get signalKindsWordWork => 'أعمال';

  @override
  String get signalKindsYesterday => 'أمس';

  @override
  String signalMapCluster(int count) {
    String _temp0 = intl.Intl.pluralLogic(
      count,
      locale: localeName,
      other: '$count عنصر هنا',
      many: '$count عنصرًا هنا',
      few: '$count عناصر هنا',
      two: 'عنصران هنا',
      one: 'عنصر واحد هنا',
      zero: 'لا عناصر هنا',
    );
    return '$_temp0';
  }

  @override
  String signalMapFerry(String name) {
    return 'العبّارة $name';
  }

  @override
  String get supportChatEmptyBody => 'اكتب سؤالك أدناه. سيصلك إشعار عندما نرد.';

  @override
  String get supportChatEmptyTitle => 'كيف يمكننا المساعدة؟';

  @override
  String get supportChatHint => 'اكتب رسالة';

  @override
  String get supportChatLoadFailed => 'تعذّر تحميل المحادثة. تحقق من الاتصال.';

  @override
  String get supportChatRetry => 'حاول مرة أخرى';

  @override
  String get supportChatSend => 'إرسال';

  @override
  String get supportChatSendFailed => 'لم تُرسل الرسالة. حاول مرة أخرى.';

  @override
  String get supportChatSubtitle => 'نرد في أقرب وقت ممكن';

  @override
  String get supportChatTitle => 'الدعم';

  @override
  String get tipDetailPartsChipCancelled => 'ملغاة';

  @override
  String get tipDetailPartsChipDelayed => 'متأخرة';

  @override
  String tipDetailPartsChipDelayedBy(String delay) {
    return 'متأخرة $delay';
  }

  @override
  String tipDetailPartsNewClock(String clock) {
    return '← $clock';
  }

  @override
  String get tipReportCancel => 'إلغاء';

  @override
  String get tipReportFailed => 'تعذّر إرسال البلاغ. حاول مرة أخرى.';

  @override
  String get tipReportHint => 'شرح اختياري';

  @override
  String get tipReportIntro =>
      'أخبرنا باختصار ما الخطأ، مثلاً مكان غير صحيح أو أن المشكلة انتهت بالفعل.';

  @override
  String get tipReportReceived => 'تم استلام البلاغ — شكراً.';

  @override
  String get tipReportSend => 'إرسال البلاغ';

  @override
  String get tipReportThanks => 'شكراً — سنراجع التنبيه.';

  @override
  String get tipReportTitle => 'الإبلاغ عن تنبيه خاطئ';

  @override
  String tipSheetAffectedParty(String party) {
    return 'الجهة المعنية: $party';
  }

  @override
  String get tipSheetAlternativeTraffic => 'وسيلة نقل بديلة';

  @override
  String get tipSheetCircumstances => 'ظروف خاصة';

  @override
  String tipSheetClockAt(String clock) {
    return 'الساعة $clock';
  }

  @override
  String get tipSheetClose => 'إغلاق';

  @override
  String get tipSheetCompensationDisclaimer =>
      'يُطبَّق المبلغ عند استيفاء شروط شركة النقل. لا نستطيع تقييم الرحلة الفردية.';

  @override
  String tipSheetCompensationLink(String operator) {
    return 'اقرأ القواعد لدى $operator';
  }

  @override
  String get tipSheetCompensationTitle => 'تعويض التاكسي';

  @override
  String get tipSheetDriveThere => 'اذهب إلى هناك';

  @override
  String get tipSheetEnded => 'انتهى';

  @override
  String tipSheetEndedAgo(String span) {
    return 'انتهى قبل $span';
  }

  @override
  String get tipSheetEndedBanner => 'انتهى. لم يعد التنبيه صالحاً.';

  @override
  String get tipSheetEndedJustNow => 'انتهى للتو';

  @override
  String get tipSheetGotFare => 'حصلت على راكب';

  @override
  String get tipSheetHide => 'إخفاء';

  @override
  String tipSheetLineTo(String line, String to) {
    return '$line ← $to';
  }

  @override
  String get tipSheetMinorNote =>
      'رسالة عامة. لا نقيّم ما إذا كان الذهاب إلى هناك مجدياً.';

  @override
  String get tipSheetNavFailed => 'تعذّر فتح الملاحة.';

  @override
  String get tipSheetNoCustomer => 'لا يوجد زبون';

  @override
  String get tipSheetNoDescription => 'لا يوجد وصف إضافي.';

  @override
  String get tipSheetOpenNavigation => 'فتح الملاحة';

  @override
  String get tipSheetOperatorFallback => 'شركة النقل';

  @override
  String get tipSheetReadMore => 'اقرأ المزيد';

  @override
  String get tipSheetReported => 'تم الإبلاغ';

  @override
  String get tipSheetRoadAdvice => 'توقع ازدحاماً، أو اختر طريقاً آخر.';

  @override
  String get tipSheetSave => 'حفظ التنبيه';

  @override
  String get tipSheetSectionEvent => 'الحدث والوصف';

  @override
  String get tipSheetSectionNotice => 'رسالة شركة النقل';

  @override
  String get tipSheetSectionRoad => 'الطريق إلى هناك';

  @override
  String get tipSheetShowAllReasons => 'عرض كل الأسباب';

  @override
  String get tipSheetShowFewerReasons => 'عرض أسباب أقل';

  @override
  String get tipSheetShowFullText => 'عرض النص كاملاً';

  @override
  String get tipSheetShowLess => 'عرض أقل';

  @override
  String get tipSheetSourcePage => 'صفحة شركة النقل';

  @override
  String tipSheetStartedAgo(String span) {
    return 'بدأ قبل $span';
  }

  @override
  String get tipSheetStartedJustNow => 'بدأ للتو';

  @override
  String tipSheetStartsIn(String span) {
    return 'يبدأ بعد $span';
  }

  @override
  String get tipSheetStartsNow => 'يبدأ الآن';

  @override
  String get tipSheetStatusNotice => 'إشعار';

  @override
  String get tipSheetStatusStopped => 'توقف الحركة';

  @override
  String get tipSheetTaxiPaid => 'التاكسي مدفوع';

  @override
  String get tipSheetUnsave => 'إزالة من المحفوظات';

  @override
  String get vehicleSessionAnotherPhone => 'هاتف آخر';

  @override
  String get vehicleSessionCancel => 'إلغاء';

  @override
  String get vehicleSessionCar => 'سيارة';

  @override
  String vehicleSessionCountiesCount(int count) {
    String _temp0 = intl.Intl.pluralLogic(
      count,
      locale: localeName,
      other: '$count مقاطعة',
      many: '$count مقاطعة',
      few: '$count مقاطعات',
      two: 'مقاطعتان',
      one: 'مقاطعة واحدة',
      zero: 'لا مقاطعات',
    );
    return '$_temp0';
  }

  @override
  String get vehicleSessionDrive => 'قُد';

  @override
  String get vehicleSessionLeave => 'مغادرة السيارة';

  @override
  String get vehicleSessionNoVehicles =>
      'الهاتف غير مرتبط بأي سيارة. اطلب من مديرك دعوتك عبر بريدك الإلكتروني، ثم سجّل الدخول كسائق.';

  @override
  String get vehicleSessionSubtitle =>
      'التنبيهات خاصة بمقاطعات السيارة. يمكن أن يكون للسيارة هاتف واحد فقط في كل مرة.';

  @override
  String get vehicleSessionTakeOver => 'تولّي';

  @override
  String vehicleSessionTakeOverBody(String message) {
    return '$message\n\nسيتوقف الهاتف الآخر عن عرض التنبيهات لهذه السيارة فورًا.';
  }

  @override
  String get vehicleSessionTakeOverCar => 'تولّي السيارة';

  @override
  String vehicleSessionTakeOverTitle(String plate) {
    return 'هل تريد تولّي $plate؟';
  }

  @override
  String get vehicleSessionTheCar => 'السيارة';

  @override
  String get vehicleSessionTitle => 'أي سيارة تقود؟';

  @override
  String vehicleSessionUsedBy(String name) {
    return 'تستخدمها $name';
  }

  @override
  String get vehicleSessionYouDriveThis => 'أنت تقود هذه السيارة';
}
