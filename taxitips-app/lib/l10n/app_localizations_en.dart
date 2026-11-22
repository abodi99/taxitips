// ignore: unused_import
import 'package:intl/intl.dart' as intl;
import 'app_localizations.dart';

// ignore_for_file: type=lint

/// The translations for English (`en`).
class AppLocalizationsEn extends AppLocalizations {
  AppLocalizationsEn([String locale = 'en']) : super(locale);

  @override
  String get alertFeedbackGotFare => 'Got a fare';

  @override
  String get alertFeedbackNoCustomer => 'No customer';

  @override
  String get alertFeedbackQueued => 'Saved. Will be sent when you have signal.';

  @override
  String get alertFeedbackSaveFailed =>
      'Could not save your answer. Try again.';

  @override
  String get alertFeedbackThanks => 'Thanks!';

  @override
  String get alertFeedbackTitle => 'How did it go?';

  @override
  String get apiClientAccountCreatedOffline =>
      'The account is created, but we could not reach the server. Log in when you have a connection again.';

  @override
  String apiClientAuthError(String details) {
    return 'Auth error: $details';
  }

  @override
  String get apiClientBankIdUnavailable => 'BankID is not available right now.';

  @override
  String get apiClientBaseUrlMissing =>
      'API_BASE_URL is not set. Pairing and car selection need the TaxiTips backend.';

  @override
  String get apiClientCannotDeleteAccount =>
      'The account cannot be deleted right now. Try again later.';

  @override
  String get apiClientCouldNotCreateAccount => 'Could not create the account';

  @override
  String apiClientDatabaseError(String details) {
    return 'Database error: $details';
  }

  @override
  String get apiClientFavoritesNeedBackend =>
      'Favorites need the Django backend';

  @override
  String get apiClientInvalidTransferCode => 'Invalid transfer code';

  @override
  String get apiClientInvalidVerificationCode =>
      'The verification code is invalid';

  @override
  String get apiClientLoginFailed => 'Could not log in. Try again.';

  @override
  String get apiClientLoginRequired => 'Log in to continue.';

  @override
  String get apiClientNoCompany => 'No company';

  @override
  String get apiClientNoDevice => 'No device';

  @override
  String get apiClientNoDeviceKey => 'The server did not give a device key.';

  @override
  String get apiClientNoDevicePush =>
      'No device — log in via the backend for push';

  @override
  String get apiClientNoDeviceToName => 'No device to name.';

  @override
  String get apiClientNoValidSession =>
      'The login did not give a valid session.';

  @override
  String get apiClientNotLoggedIn => 'Not logged in';

  @override
  String get apiClientNotifyLineDelayedHelp =>
      'Usually a weak signal -- off by default.';

  @override
  String get apiClientNotifyLineDelayedLabel => 'Delays';

  @override
  String get apiClientNotifyLineDelayedShort => 'The line runs, but is delayed';

  @override
  String get apiClientNotifyLinePausedHelp =>
      'The best chance that people need a taxi.';

  @override
  String get apiClientNotifyLinePausedLabel =>
      'The whole line is at a standstill';

  @override
  String get apiClientNotifyLinePausedShort => 'No traffic at all on the line';

  @override
  String get apiClientNotifyNeedsServer =>
      'The notification settings need the TaxiTips server.';

  @override
  String get apiClientNotifyRoadAccidentHelp =>
      'Mostly affects drivers already on the road, but good to know.';

  @override
  String get apiClientNotifyRoadAccidentLabel => 'Accident or closed road';

  @override
  String get apiClientNotifyRoadShort => 'Road traffic';

  @override
  String get apiClientNotifyRoadWorkHelp =>
      'Rarely a taxi signal -- off by default.';

  @override
  String get apiClientNotifyRoadWorkLabel => 'Roadworks or queues';

  @override
  String get apiClientNotifyVehicleCancelledHelp =>
      'Fewer people affected, but may still be worth a look.';

  @override
  String get apiClientNotifyVehicleCancelledLabel =>
      'A single departure cancelled';

  @override
  String get apiClientNotifyVehicleCancelledShort =>
      'One departure cancelled, the others run as usual';

  @override
  String get apiClientOnDutyNeedsBackend => 'On duty needs the new backend';

  @override
  String get apiClientPhoneNotPaired => 'The phone is not paired.';

  @override
  String get apiClientSupportChatUnavailable =>
      'Support chat is not available here.';

  @override
  String get appMainLogout => 'Log out';

  @override
  String get appMainSomethingWrong => 'Something went wrong.';

  @override
  String get appMainTrialNotStarted =>
      'The account was created but the trial could not start. Contact TaxiTips.';

  @override
  String get appMainTryAgain => 'Try again';

  @override
  String get bankIdFlowAppNotFound =>
      'We cannot find the BankID app on this phone. Scan the code with BankID on another phone.';

  @override
  String get bankIdFlowApproveInApp =>
      'Approve in the BankID app. Then come back here.';

  @override
  String get bankIdFlowBadEmail => 'Wrong email.';

  @override
  String get bankIdFlowCancel => 'Cancel';

  @override
  String get bankIdFlowChangeEmail => 'Change email too';

  @override
  String get bankIdFlowFailed => 'Identification failed. Try again.';

  @override
  String bankIdFlowHello(String name) {
    return 'Hi $name!';
  }

  @override
  String get bankIdFlowHidePassword => 'Hide password';

  @override
  String get bankIdFlowNewEmail => 'New email';

  @override
  String get bankIdFlowNewPasswordTitle => 'New password';

  @override
  String get bankIdFlowNoAccountHelp =>
      'Your BankID has no account here.\n\nDid you get an invitation from your taxi company? Ask them to send the invitation again. You will then get an email where you choose a new password.\n\nDo you not have an account? Tap Create account.';

  @override
  String get bankIdFlowNoAccountTitle => 'We cannot find an account';

  @override
  String get bankIdFlowNoResponse =>
      'BankID is not responding right now. Try again.';

  @override
  String get bankIdFlowOk => 'OK';

  @override
  String get bankIdFlowOpenBankId => 'Open BankID';

  @override
  String get bankIdFlowOtherPhone => 'BankID on another phone';

  @override
  String get bankIdFlowPasswordHelper => 'At least 8 characters';

  @override
  String get bankIdFlowPasswordMin => 'Password: at least 8 characters.';

  @override
  String get bankIdFlowQrLabel => 'QR code for BankID';

  @override
  String get bankIdFlowSave => 'Save';

  @override
  String get bankIdFlowScanOnOther =>
      'Open BankID on your other phone and scan the code.';

  @override
  String get bankIdFlowShowPassword => 'Show password';

  @override
  String get bankIdFlowSomethingWrong => 'Something went wrong. Try again.';

  @override
  String get bankIdFlowThisPhone => 'BankID on this phone';

  @override
  String get bankIdFlowTooLong => 'It took too long. Try again.';

  @override
  String get bankIdFlowTryAgain => 'Try again';

  @override
  String get bankIdFlowYourAccount => 'Your account:';

  @override
  String get categoryBarAll => 'All';

  @override
  String get categoryBarSaved => 'Saved';

  @override
  String get companySettingsActiveTitle => 'Active';

  @override
  String get companySettingsAdd => 'Add';

  @override
  String get companySettingsAddCar => 'Add a car';

  @override
  String get companySettingsAlreadyConnected => 'Already connected';

  @override
  String get companySettingsBlock => 'Block';

  @override
  String get companySettingsBlockBody =>
      'The phone stops showing tips right away and leaves the car. The driver needs a new invitation to get back in.';

  @override
  String get companySettingsBlockPhone => 'Block the phone';

  @override
  String companySettingsBlockTitle(String label) {
    return 'Block $label?';
  }

  @override
  String get companySettingsCancel => 'Cancel';

  @override
  String get companySettingsCar => 'Car';

  @override
  String companySettingsCarAdded(String plate) {
    return '$plate is added';
  }

  @override
  String get companySettingsCarMissingOnLicense =>
      'The car is missing on the license. Contact support.';

  @override
  String companySettingsCarRemoved(String plate) {
    return '$plate is removed';
  }

  @override
  String companySettingsCars(int used, int limit) {
    String _temp0 = intl.Intl.pluralLogic(
      limit,
      locale: localeName,
      other: 'cars',
      one: 'car',
    );
    return '$used of $_temp0';
  }

  @override
  String get companySettingsCarsLabel => 'Cars';

  @override
  String companySettingsChangeAgainNextMonth(String label) {
    return '$label\nYou can change county again next month.';
  }

  @override
  String companySettingsChangeUsesOne(String label) {
    return '$label. One change uses one of them.';
  }

  @override
  String get companySettingsCouldNotReadCompany =>
      'Could not load the company.';

  @override
  String companySettingsCountyChangesLeft(int remaining, int total) {
    return 'County changes left this month: $remaining of $total';
  }

  @override
  String get companySettingsCountyNotChangeable =>
      'The county cannot be changed in the app.';

  @override
  String get companySettingsCountyWhereCarDrives =>
      'County where the car drives';

  @override
  String companySettingsDaysLeft(int days) {
    String _temp0 = intl.Intl.pluralLogic(
      days,
      locale: localeName,
      other: '$days days left',
      one: '1 day left',
    );
    return '$_temp0';
  }

  @override
  String get companySettingsDriveMyself => 'Drive myself with this phone';

  @override
  String get companySettingsDriver => 'Driver';

  @override
  String get companySettingsDriverEmail => 'Driver email';

  @override
  String get companySettingsDriverEmailError =>
      'Enter the driver email, e.g. name@example.com';

  @override
  String get companySettingsDriverName => 'Driver name';

  @override
  String get companySettingsDriverNameOptional => 'Driver name (optional)';

  @override
  String get companySettingsDrivers => 'Drivers';

  @override
  String companySettingsDriversCount(int count) {
    String _temp0 = intl.Intl.pluralLogic(
      count,
      locale: localeName,
      other: '$count drivers',
      one: '1 driver',
    );
    return '$_temp0';
  }

  @override
  String companySettingsDrivingBy(String name) {
    return 'Driving: $name';
  }

  @override
  String get companySettingsDrivingNow => 'Driving now';

  @override
  String companySettingsGraceLine(String date) {
    return 'Tips work until $date.';
  }

  @override
  String get companySettingsGraceTitle => 'Membership will pause soon';

  @override
  String get companySettingsInviteByEmail => 'Invite a driver by email';

  @override
  String get companySettingsInviteDriverBody =>
      'The driver gets an email, chooses a password and logs in to the app. The phone is then connected to the car.';

  @override
  String companySettingsInviteDriverTitle(String plate) {
    return 'Invite a driver to $plate';
  }

  @override
  String get companySettingsInviteExpired => 'The invitation has expired';

  @override
  String get companySettingsInviteRemoved => 'The invitation is removed';

  @override
  String companySettingsInviteResent(String email) {
    return 'Invitation sent again to $email';
  }

  @override
  String companySettingsInviteSent(String email) {
    return 'Invitation sent to $email';
  }

  @override
  String companySettingsInvitedCount(int count) {
    String _temp0 = intl.Intl.pluralLogic(
      count,
      locale: localeName,
      other: '$count invited',
      one: '1 invited',
    );
    return '$_temp0';
  }

  @override
  String get companySettingsInvitedNotLoggedIn =>
      'Invited · has not logged in yet';

  @override
  String get companySettingsLastDay => 'Last day';

  @override
  String get companySettingsLoadFailedPull =>
      'Could not load the company right now. Pull down to try again.';

  @override
  String get companySettingsMonthsShort =>
      'Jan,Feb,Mar,Apr,May,Jun,Jul,Aug,Sep,Oct,Nov,Dec';

  @override
  String get companySettingsMore => 'More';

  @override
  String get companySettingsNameHint => 'e.g. Anna';

  @override
  String get companySettingsNoCars => 'No cars';

  @override
  String get companySettingsNoChangesLeft =>
      'No county changes left this month.';

  @override
  String get companySettingsNoCounty => 'No county';

  @override
  String get companySettingsNoDriver => 'No driver';

  @override
  String get companySettingsNoDriverConnected => 'No driver connected';

  @override
  String companySettingsNowDrives(String plate) {
    return 'This phone is now driving $plate';
  }

  @override
  String companySettingsNowDrivesIn(String plate, String county) {
    return '$plate now drives in $county';
  }

  @override
  String get companySettingsOnlyAdminChanges =>
      'Only an administrator can change county.';

  @override
  String companySettingsPairedPickCar(String plate) {
    return 'The phone is connected to $plate. Pick the car in the list.';
  }

  @override
  String get companySettingsPausedTitle => 'Paused';

  @override
  String get companySettingsPhoneBlocked => 'The phone is blocked';

  @override
  String get companySettingsPlateLabel => 'Registration number';

  @override
  String get companySettingsRemove => 'Remove';

  @override
  String get companySettingsRemoveCar => 'Remove the car';

  @override
  String get companySettingsRemoveCarBody =>
      'The drivers in the car stop getting tips right away. The seat in the trial becomes free.';

  @override
  String companySettingsRemoveCarTitle(String plate) {
    return 'Remove $plate?';
  }

  @override
  String get companySettingsRename => 'Rename';

  @override
  String companySettingsRenewsLine(String date) {
    return 'Renews $date';
  }

  @override
  String get companySettingsResendInvite => 'Send again';

  @override
  String get companySettingsRetry => 'Try again';

  @override
  String companySettingsRevokeBody(String email) {
    return '$email can no longer use the invitation to log in.';
  }

  @override
  String get companySettingsRevokeInvite => 'Remove the invitation';

  @override
  String get companySettingsRevokeTitle => 'Remove the invitation?';

  @override
  String get companySettingsSave => 'Save';

  @override
  String get companySettingsSendInvite => 'Send invitation';

  @override
  String get companySettingsSuspendedLine => 'Contact us in the chat.';

  @override
  String get companySettingsSuspendedTitle => 'Suspended';

  @override
  String get companySettingsTapToChangeCounty => 'Tap to change county';

  @override
  String get companySettingsTheCar => 'the car';

  @override
  String get companySettingsThePhone => 'the phone';

  @override
  String get companySettingsThisPhone => 'This phone';

  @override
  String get companySettingsTipsPaused => 'Tips are paused.';

  @override
  String get companySettingsTrialAllIncluded =>
      'Everything in the app is included during the trial.';

  @override
  String companySettingsTrialContinuesLine(String until, String cars) {
    return 'The membership continues after the trial · $until · $cars';
  }

  @override
  String get companySettingsTrialEndedTitle => 'The trial has ended';

  @override
  String companySettingsTrialLine(String until, String cars) {
    return '$until · $cars';
  }

  @override
  String get companySettingsTrialLockedNotIncluded =>
      'Anything with a lock in the app is not part of the trial.';

  @override
  String companySettingsTrialPendingLine(String cars) {
    return 'Starts when the first phone is connected · $cars';
  }

  @override
  String get companySettingsTrialTitle => 'Trial period';

  @override
  String companySettingsTrialUntil(String date) {
    return 'The trial is valid until $date.';
  }

  @override
  String get companySettingsWhereDoesCarDrive => 'Where does the car drive?';

  @override
  String get companySettingsYourCompany => 'Your company';

  @override
  String get countyChecklistAllCounties =>
      'You see tips from all counties in the membership. Untick the ones you do not want to see.';

  @override
  String get countyChecklistChangeTrialCounty => 'Change the trial county';

  @override
  String get countyChecklistDone => 'Done';

  @override
  String get countyChecklistNoCounties => 'The membership has no counties yet.';

  @override
  String countyChecklistSomeCounties(int selected, int total) {
    return 'You see tips from $selected of $total counties.';
  }

  @override
  String get countyChecklistTitle => 'Your counties';

  @override
  String get driverScreenAccessInactive => 'Access is not active.';

  @override
  String get driverScreenAllCountiesSelected =>
      'All your counties are selected. Untick the ones you do not want to see.';

  @override
  String get driverScreenAllTips => 'All tips';

  @override
  String driverScreenAllYourCounties(int count) {
    return 'All your counties ($count)';
  }

  @override
  String get driverScreenArea => 'Area';

  @override
  String get driverScreenBack => 'Back';

  @override
  String get driverScreenBlockedBody => 'Contact TaxiTips support.';

  @override
  String get driverScreenBlockedTitle => 'The account is suspended';

  @override
  String get driverScreenCalm => 'Calm right now';

  @override
  String get driverScreenCancelled => 'Cancelled';

  @override
  String driverScreenCategoryLocked(String category) {
    return '$category is not included in the trial';
  }

  @override
  String get driverScreenChoose => 'Choose';

  @override
  String get driverScreenChooseAreaText =>
      'Choose your driving area to see tips.';

  @override
  String get driverScreenChooseCar => 'Choose which car you drive to see tips.';

  @override
  String get driverScreenChooseCarAction => 'Choose car';

  @override
  String get driverScreenChooseCarFirstCounties =>
      'Choose a car first. The car\'s counties are then shown here.';

  @override
  String get driverScreenClear => 'Clear';

  @override
  String get driverScreenClearFilters => 'Clear filters';

  @override
  String get driverScreenConnectingPhone => 'Connecting phone…';

  @override
  String get driverScreenCountiesAndMunicipalities =>
      'Counties and municipalities';

  @override
  String get driverScreenDayToday => 'Today';

  @override
  String get driverScreenDayTomorrow => 'Tomorrow';

  @override
  String get driverScreenDayWeekend => 'The weekend';

  @override
  String driverScreenDays(int count) {
    String _temp0 = intl.Intl.pluralLogic(
      count,
      locale: localeName,
      other: '$count days',
      one: '1 day',
    );
    return '$_temp0';
  }

  @override
  String get driverScreenDone => 'Done';

  @override
  String get driverScreenDrivingArea => 'Driving area';

  @override
  String get driverScreenDrivingAreaText =>
      'The counties you drive in. Notifications, and the list when the app does not have your location, follow the driving area.';

  @override
  String get driverScreenEvents => 'Events';

  @override
  String get driverScreenEventsFailed => 'Cannot get events right now.';

  @override
  String get driverScreenEventsToday => 'Events today';

  @override
  String get driverScreenFerries => 'Ferries';

  @override
  String get driverScreenFetchingPosition => 'Getting position…';

  @override
  String get driverScreenFilter => 'Filter';

  @override
  String get driverScreenGpsOff =>
      'Turn on location (GPS) in the phone settings';

  @override
  String get driverScreenGpsTimeout =>
      'GPS took too long — try outdoors or try again';

  @override
  String get driverScreenGroupMedium => 'Medium';

  @override
  String get driverScreenGroupOther => 'Other';

  @override
  String get driverScreenGroupStrong => 'Strong';

  @override
  String driverScreenGroupTitle(String name, int count) {
    return '$name · $count';
  }

  @override
  String get driverScreenGroupWeak => 'Weak';

  @override
  String driverScreenHidden(String types) {
    return 'Hidden: $types';
  }

  @override
  String driverScreenHiddenTiers(int count) {
    String _temp0 = intl.Intl.pluralLogic(
      count,
      locale: localeName,
      other: '$count disruption types hidden',
      one: '1 disruption type hidden',
    );
    return '$_temp0';
  }

  @override
  String get driverScreenHistory => 'History';

  @override
  String driverScreenKm(int km) {
    return '$km km';
  }

  @override
  String get driverScreenLegend => 'What do the symbols mean?';

  @override
  String get driverScreenLocationAllow =>
      'Allow location for TaxiTips in the phone settings';

  @override
  String get driverScreenLocationDenied => 'Location permission was denied';

  @override
  String get driverScreenLocationTimeout => 'Location took too long';

  @override
  String driverScreenLockedCount(int count) {
    String _temp0 = intl.Intl.pluralLogic(
      count,
      locale: localeName,
      other: 'There are $count such tips in your area right now.',
      one: 'There is 1 such tip in your area right now.',
    );
    return '$_temp0';
  }

  @override
  String get driverScreenLoginInvalid =>
      'The login does not work. Log in again.';

  @override
  String get driverScreenMoreDates => 'More dates';

  @override
  String get driverScreenMoreOptions => 'More options: hide types';

  @override
  String get driverScreenMovedBody =>
      'Your account is now used on another phone. Log in here again if you want to move back. The phone can be changed once a month.';

  @override
  String get driverScreenMovedTitle => 'Logged in on another phone';

  @override
  String driverScreenMunicipalitiesChosen(int count) {
    String _temp0 = intl.Intl.pluralLogic(
      count,
      locale: localeName,
      other: '$count municipalities selected',
      one: '1 municipality selected',
    );
    return '$_temp0';
  }

  @override
  String get driverScreenMyPosition => 'My position';

  @override
  String get driverScreenNavFailed => 'Could not open navigation.';

  @override
  String get driverScreenNearMe => 'Near me';

  @override
  String get driverScreenNearYou => 'Near you';

  @override
  String get driverScreenNearYou25 => 'Near you (25 km)';

  @override
  String get driverScreenNeedsInternet =>
      'Needs internet. Try again when you have a connection.';

  @override
  String get driverScreenNoAccess =>
      'The phone has no access. Log in again, or ask your manager to invite you.';

  @override
  String get driverScreenNoCountiesYet =>
      'No counties yet. Choose a car first.';

  @override
  String get driverScreenNoCounty => 'No county selected';

  @override
  String get driverScreenNoEventsDays => 'No events on these days.';

  @override
  String driverScreenNoEventsWithin(int km) {
    return 'No events within $km km. Choose a longer distance.';
  }

  @override
  String get driverScreenNoFerries => 'No ferries on their way in right now.';

  @override
  String driverScreenNoNewTips(String web) {
    return 'New tips are not shown right now. $web This is not the same as \"no disruptions right now\".';
  }

  @override
  String get driverScreenNoRoadAccidents =>
      'No traffic accidents in your area right now.';

  @override
  String get driverScreenNoTipsFilters => 'No tips with these filters.';

  @override
  String driverScreenNotUpdated(String time) {
    return 'Not updated since $time';
  }

  @override
  String get driverScreenNothingSaved =>
      'Nothing saved yet.\n\nTap ☆ on a tip or an event. Tips are saved for seven days; events until the day after.';

  @override
  String get driverScreenNow => 'Now';

  @override
  String get driverScreenOnlyStrong => 'Only strong';

  @override
  String get driverScreenOnlyStrongest => 'Only strongest';

  @override
  String get driverScreenOpenSettings => 'Open settings';

  @override
  String driverScreenPausedBody(String notice) {
    return '$notice This is not the same as \"no disruptions right now\".';
  }

  @override
  String get driverScreenPausedTitle => 'The membership is paused';

  @override
  String get driverScreenPhonePaired => 'Phone connected';

  @override
  String get driverScreenPositionFailed => 'Could not get your position';

  @override
  String get driverScreenPositionFailedShort => 'Could not get position';

  @override
  String get driverScreenPresetAll => 'All';

  @override
  String get driverScreenPresetStrong => 'Strong';

  @override
  String get driverScreenPresetStrongest => 'Strongest';

  @override
  String driverScreenRecentlyOver(int count) {
    return 'Just ended ($count)';
  }

  @override
  String get driverScreenRemovedSnack => 'Removed from saved.';

  @override
  String get driverScreenResetFilter => 'Reset filters';

  @override
  String get driverScreenRoadOnly =>
      'Only traffic accidents. Roadworks and closures are not shown.';

  @override
  String get driverScreenSaveFailed => 'Could not save the tip';

  @override
  String get driverScreenSaved => 'Saved';

  @override
  String get driverScreenSavedSnack =>
      'Saved. Shown under ⭐ Saved for seven days.';

  @override
  String get driverScreenSectionTips => 'Tips';

  @override
  String get driverScreenSeeSettings => 'See settings';

  @override
  String get driverScreenSettings => 'Settings';

  @override
  String get driverScreenSettingsNewReply =>
      'Settings – new reply from support';

  @override
  String get driverScreenShow => 'Show';

  @override
  String get driverScreenShowAll => 'Show all';

  @override
  String get driverScreenShowDistance => 'Show distance';

  @override
  String get driverScreenShowFullList => 'Show the full list';

  @override
  String get driverScreenShowMap => 'Show the map';

  @override
  String get driverScreenSort => 'Sort';

  @override
  String get driverScreenSortImportant => 'Most important';

  @override
  String get driverScreenSortNearest => 'Nearest';

  @override
  String get driverScreenSortNewest => 'Newest';

  @override
  String get driverScreenStrength => 'Strength';

  @override
  String driverScreenStrengthRange(int min, int max) {
    return 'Strength $min–$max';
  }

  @override
  String get driverScreenTipGone =>
      'The tip no longer exists, or the car does not have access to it.';

  @override
  String get driverScreenTipsPausedTitle => 'Tips are paused';

  @override
  String get driverScreenTrialEndedTitle => 'The trial has ended';

  @override
  String get driverScreenTrialNotStartedBody =>
      'Choose counties under Settings. Drivers are invited on the web. The trial starts when the first driver logs in.';

  @override
  String get driverScreenTrialNotStartedTitle => 'Welcome! One step left';

  @override
  String get driverScreenUnsaveFailed => 'Could not remove the tip';

  @override
  String get driverScreenWholeCounty => 'Whole county · choose municipalities';

  @override
  String get driverScreenWholeCountyShort => 'The whole county';

  @override
  String get driverScreenWithin25 => 'Within about 25 km';

  @override
  String get driverScreenYellowShown => 'Yellow = shown. Tap to hide.';

  @override
  String get driverScreenZoomIn => 'Zoom in';

  @override
  String get driverScreenZoomOut => 'Zoom out';

  @override
  String get driverTourCategoriesText =>
      'Choose what you want to see: train and bus, road, flights, ferry or events. The number is how many tips. Saved shows the tips you have saved.';

  @override
  String get driverTourCategoriesTitle => 'Categories';

  @override
  String get driverTourDrive => 'Drive there';

  @override
  String get driverTourFilterText =>
      'With Filter you choose county, how strong tips you want to see and what to hide. Choose your county here to get tips from there.';

  @override
  String get driverTourFilterTitle => 'Filter and county';

  @override
  String get driverTourHowWasIt => 'How did it go?';

  @override
  String get driverTourListText =>
      'These are the tips near you. The strongest is at the top. Pull the list up to see more.';

  @override
  String get driverTourListTitle => 'The tip list';

  @override
  String get driverTourMapText =>
      'Each pin is a tip. The pin has the same color as the tip. Tap a pin to open the tip. At the top, the question mark explains the symbols, and the clock in the corner is History: the tips from the last 24 hours.';

  @override
  String get driverTourMapTitle => 'The map and the pins';

  @override
  String get driverTourSave => 'Save';

  @override
  String get driverTourSettingsDriver =>
      'Here you turn on notifications and choose the car you drive. Notifications tell you when a strong tip appears near you. The tour stays available under Help.';

  @override
  String get driverTourSettingsOwner =>
      'Here you choose county and turn on notifications. Drivers are invited on the web. Here you also choose which place you drive with. The tour stays available under Help.';

  @override
  String get driverTourSettingsTitle => 'Settings';

  @override
  String get driverTourStrengthText =>
      'Every tip has a color and a word. At the bottom of the list is \"Other\": messages from transport companies. That is information, not tips.';

  @override
  String get driverTourStrengthTitle => 'The color shows the strength';

  @override
  String get driverTourTipText =>
      'A sheet opens with more about the tip. There you can drive there, save the tip and answer how it went. Your answers make the tips better.';

  @override
  String get driverTourTipTitle => 'Tap a tip';

  @override
  String get eventsScreenAllCounties => 'All counties';

  @override
  String get eventsScreenAllKinds => 'All types';

  @override
  String eventsScreenCount(int count) {
    String _temp0 = intl.Intl.pluralLogic(
      count,
      locale: localeName,
      other: '$count events',
      one: '$count event',
    );
    return '$_temp0';
  }

  @override
  String eventsScreenError(String error) {
    return 'Could not load the events: $error';
  }

  @override
  String get eventsScreenFollowing =>
      'You are following the event. It is under ⭐ Saved on the map.';

  @override
  String eventsScreenLoading(String period) {
    return 'Loading $period…';
  }

  @override
  String get eventsScreenMonth => '30 days';

  @override
  String eventsScreenNone(String period) {
    return 'No events $period in your area.';
  }

  @override
  String get eventsScreenNoneHint =>
      'The days above have events — tap one of them, or pick a longer period.';

  @override
  String get eventsScreenNoneThin =>
      'There are few events outside the big cities. Try another county.';

  @override
  String get eventsScreenOtherKind => 'Other';

  @override
  String get eventsScreenPickDay => 'Pick a day';

  @override
  String get eventsScreenPickPeriod => 'Pick a period';

  @override
  String get eventsScreenQuarter => '3 months';

  @override
  String get eventsScreenSortLargest => 'Largest';

  @override
  String get eventsScreenSortNearest => 'Nearest';

  @override
  String get eventsScreenSortTime => 'Time';

  @override
  String eventsScreenSummary(String count, String period) {
    return '$count · $period';
  }

  @override
  String eventsScreenSummaryFiltered(int shown, int total, String period) {
    return '$shown of $total events · $period';
  }

  @override
  String get eventsScreenTitle => 'Events';

  @override
  String get eventsScreenToday => 'Today';

  @override
  String get eventsScreenTodayPrefix => 'Today · ';

  @override
  String get eventsScreenTomorrow => 'Tomorrow';

  @override
  String get eventsScreenTomorrowPrefix => 'Tomorrow · ';

  @override
  String get eventsScreenUnfollowed => 'You no longer follow it.';

  @override
  String get eventsScreenWeek => '7 days';

  @override
  String get eventsScreenWeekend => 'Weekend';

  @override
  String get eventsScreenWholeArea => 'Whole area';

  @override
  String get ferryEventApproaching => 'Coming in';

  @override
  String get ferryEventAtQuay => 'At the quay';

  @override
  String ferryEventAtQuaySince(String clock) {
    return 'At the quay since $clock';
  }

  @override
  String ferryEventAtTime(String time) {
    return 'At $time';
  }

  @override
  String get ferryEventByTimetable => 'According to timetable';

  @override
  String get ferryEventConfirmed => 'Confirmed';

  @override
  String get ferryEventConfirmedApproaching =>
      'Confirmed – the ship is coming in';

  @override
  String get ferryEventConfirmedBerthed =>
      'Confirmed – the ship is at the quay';

  @override
  String ferryEventDistance(String distance, String time) {
    return '$distance · about $time by car';
  }

  @override
  String get ferryEventDockingNow => 'Docking now';

  @override
  String ferryEventDocksAt(String clock, String relative) {
    return 'Docks $clock · $relative';
  }

  @override
  String ferryEventEarly(String time) {
    return '$time early';
  }

  @override
  String get ferryEventEndEstimated =>
      'The end time is an estimate, not given by the organiser.';

  @override
  String ferryEventEndsAbout(String time) {
    return 'Ends about $time';
  }

  @override
  String get ferryEventFerry => 'Ferry';

  @override
  String get ferryEventFollow => 'Follow';

  @override
  String get ferryEventFollowing => 'Following';

  @override
  String ferryEventFrom(String place) {
    return 'From $place';
  }

  @override
  String get ferryEventInternational => 'International';

  @override
  String ferryEventLate(String time) {
    return '$time late';
  }

  @override
  String get ferryEventOnTime => 'On time';

  @override
  String get ferryEventOngoing => 'Happening now';

  @override
  String ferryEventOriginDeparted(String from, String clock) {
    return '$from, departed $clock';
  }

  @override
  String ferryEventOriginDeparts(String from, String clock) {
    return '$from, departs $clock';
  }

  @override
  String ferryEventPeopleLeave(String time) {
    return 'People leave until $time';
  }

  @override
  String ferryEventPickupNow(String clock) {
    return 'People are coming out now, until $clock';
  }

  @override
  String ferryEventPickupRange(String range) {
    return 'People come out $range';
  }

  @override
  String ferryEventPickupValueNow(String clock) {
    return 'now, until $clock';
  }

  @override
  String ferryEventReachAfter(String clock) {
    return 'Arrive about $clock – after most have left';
  }

  @override
  String ferryEventReachBefore(String clock) {
    return 'Arrive about $clock – before people come out';
  }

  @override
  String ferryEventReachDuring(String clock) {
    return 'Arrive about $clock – while people come out';
  }

  @override
  String ferryEventReachNoWindow(String clock) {
    return 'Arrive about $clock';
  }

  @override
  String get ferryEventRowArrival => 'Arrival';

  @override
  String get ferryEventRowAtQuay => 'At the quay';

  @override
  String get ferryEventRowCertainty => 'How certain';

  @override
  String get ferryEventRowComingFrom => 'Coming from';

  @override
  String get ferryEventRowDelay => 'Delay';

  @override
  String get ferryEventRowDistance => 'Distance';

  @override
  String get ferryEventRowEndsAbout => 'Ends about';

  @override
  String get ferryEventRowKind => 'Type';

  @override
  String get ferryEventRowOperator => 'Shipping line';

  @override
  String get ferryEventRowPeopleCome => 'People come out';

  @override
  String get ferryEventRowPeopleLeaving => 'People leaving';

  @override
  String get ferryEventRowQuay => 'Quay';

  @override
  String get ferryEventRowReach => 'Will you make it';

  @override
  String get ferryEventRowRoute => 'Route';

  @override
  String get ferryEventRowSameQuay => 'Same quay ±30 min';

  @override
  String get ferryEventRowService => 'Service';

  @override
  String get ferryEventRowSize => 'Size';

  @override
  String get ferryEventRowStatus => 'Status';

  @override
  String get ferryEventRowTimetable => 'Timetable';

  @override
  String ferryEventSameMany(int count) {
    String _temp0 = intl.Intl.pluralLogic(
      count,
      locale: localeName,
      other: '$count more ferries arriving',
    );
    return '$_temp0';
  }

  @override
  String ferryEventSameManyFirst(int count, String at) {
    String _temp0 = intl.Intl.pluralLogic(
      count,
      locale: localeName,
      other: '$count more ferries arriving, first $at',
    );
    return '$_temp0';
  }

  @override
  String get ferryEventSameOne => '1 more ferry arriving';

  @override
  String ferryEventSameOneAt(String at) {
    return '1 more ferry arriving $at';
  }

  @override
  String get ferryEventSectionContext => 'Context';

  @override
  String get ferryEventSectionWhen => 'When';

  @override
  String get ferryEventSectionWhere => 'Where';

  @override
  String get ferryEventSectionWho => 'Who gets off';

  @override
  String ferryEventShouldHaveDocked(String clock) {
    return 'Was due to dock $clock according to timetable';
  }

  @override
  String get ferryEventSizeLarge => 'Large ferry';

  @override
  String get ferryEventSizeMedium => 'Medium-sized ferry';

  @override
  String get ferryEventSizeSmall => 'Smaller ferry';

  @override
  String get ferryEventTimeNotSet => 'Time not set';

  @override
  String get ferryEventToday => 'today';

  @override
  String get ferryEventTomorrow => 'tomorrow';

  @override
  String get ferryEventUnknown => 'unknown';

  @override
  String ferryEventVenueCapacity(String capacity) {
    return 'Venue capacity $capacity';
  }

  @override
  String ferryEventVenueCapacityNote(String capacity) {
    return 'venue capacity $capacity (capacity, not crowd)';
  }

  @override
  String get followUpCardClose => 'Close';

  @override
  String followUpCardDrove(String place, String time) {
    return 'You drove to $place $time';
  }

  @override
  String get forceUpgradeBody =>
      'This version no longer works. Update to continue.';

  @override
  String get forceUpgradeClose => 'Close';

  @override
  String get forceUpgradeNudge =>
      'A new version is available. Update when you can.';

  @override
  String get forceUpgradeTitle => 'Update the app';

  @override
  String get forceUpgradeUpdate => 'Update';

  @override
  String forceUpgradeVersions(String installed, String required) {
    return 'Your version: $installed  ·  Required: $required';
  }

  @override
  String get guidedTourDone => 'Done';

  @override
  String get guidedTourNext => 'Next';

  @override
  String get guidedTourSkip => 'Skip';

  @override
  String guidedTourStep(int position, int total) {
    return 'Step $position of $total';
  }

  @override
  String get historyScreenAnd => ' and ';

  @override
  String get historyScreenEarlier => 'Started earlier';

  @override
  String get historyScreenEnded => 'Over';

  @override
  String historyScreenHidden(int count) {
    return '$count tips are not shown.';
  }

  @override
  String historyScreenHiddenIn(int count, String categories) {
    return '$count tips in $categories are not shown.';
  }

  @override
  String historyScreenHours(int hours) {
    return '$hours h';
  }

  @override
  String get historyScreenLoadError => 'Could not load the history. Try again.';

  @override
  String get historyScreenNeedsArea =>
      'Choose your driving area to see the history.';

  @override
  String get historyScreenNoAccess =>
      'History is shown when the phone has access to tips.';

  @override
  String historyScreenNone(int hours) {
    return 'No tips in the last $hours hours.';
  }

  @override
  String get historyScreenOngoing => 'Ongoing';

  @override
  String get historyScreenRetry => 'Try again';

  @override
  String historyScreenShowingLatest(int count) {
    return 'Showing the latest $count.';
  }

  @override
  String historyScreenSummary(int count, int hours, int active) {
    return '$count tips in the last $hours hours · $active ongoing';
  }

  @override
  String get historyScreenTitle => 'History';

  @override
  String get historyScreenUnavailable =>
      'History is not available in this version.';

  @override
  String get languageButtonLabel => 'Change language';

  @override
  String languageCurrentAuto(String language) {
    return '$language (phone language)';
  }

  @override
  String get languageFollowPhone => 'Phone language';

  @override
  String languageFollowPhoneDetail(String language) {
    return 'Now: $language';
  }

  @override
  String get languageSectionDescription =>
      'The app follows your phone\'s language when it is available.';

  @override
  String get languageTitle => 'Language';

  @override
  String get loginScreenBack => 'Back';

  @override
  String get loginScreenCreateAccount => 'Create a free account';

  @override
  String get loginScreenDeviceSwapLimit =>
      'You have already changed phone once this month. Contact support and we will help you change again.';

  @override
  String get loginScreenEmail => 'Email';

  @override
  String get loginScreenEmailNotConfirmed =>
      'Confirm your email first. Tap the link in the email.';

  @override
  String get loginScreenEnterCredentials => 'Enter your email and password.';

  @override
  String get loginScreenFailed => 'Could not log in. Try again.';

  @override
  String get loginScreenForgotPassword => 'Forgot your password?';

  @override
  String get loginScreenHidePassword => 'Hide password';

  @override
  String get loginScreenIntro =>
      'For drivers, owners and office staff. New driver? First choose a password with the link in your invitation.';

  @override
  String get loginScreenNoAccount => 'No account?';

  @override
  String get loginScreenNoInvite =>
      'This account is not linked to any taxi company. Ask your boss to invite you, or tap Create a free account below.';

  @override
  String get loginScreenPassword => 'Password';

  @override
  String get loginScreenRateLimit => 'Wait a minute and try again.';

  @override
  String loginScreenRecovered(String email) {
    return 'Done! Log in with $email.';
  }

  @override
  String get loginScreenShowPassword => 'Show password';

  @override
  String get loginScreenTagline =>
      'See where people need a taxi,\nbefore the queue grows.';

  @override
  String get loginScreenTitle => 'Log in';

  @override
  String get loginScreenWithBankId => 'Log in with BankID';

  @override
  String get loginScreenWrongCredentials => 'Wrong email or password.';

  @override
  String get membershipCopyAccessNotActive => 'Access is not active.';

  @override
  String get membershipCopyInvoicesOnWeb =>
      'Invoices and membership are handled by the company\'s administrator on the web.';

  @override
  String get membershipCopyNotActive =>
      'The membership is not active right now.';

  @override
  String get membershipCopyNotInMembership =>
      'Not included in your membership.';

  @override
  String get membershipCopyNotInTrial => 'Not included in the trial.';

  @override
  String get membershipCopyOnWeb =>
      'Your company\'s administrator manages the membership on the web.';

  @override
  String get membershipCopyPaused => 'The membership is paused.';

  @override
  String get membershipCopyPortalSubtitle =>
      'Opens the customer portal on the web: cars, invoices and members.';

  @override
  String get membershipCopyPortalTitle => 'Manage company account';

  @override
  String get membershipCopyPromiseNoBinding => 'No commitment';

  @override
  String get membershipCopyPromiseNoCard => 'No card';

  @override
  String get membershipCopyPromiseNoCompany => 'No company needed';

  @override
  String get membershipCopyTrialEnded => 'The trial period has ended.';

  @override
  String get membershipCountyContinue => 'Continue';

  @override
  String get membershipCountyLoadFailed =>
      'Could not load the counties. Pull down to try again.';

  @override
  String get membershipCountyRetry => 'Try again';

  @override
  String get membershipCountySubtitle =>
      'Choose the county where you drive the most. You can change later.';

  @override
  String get membershipCountyTitle => 'Where do you want to drive?';

  @override
  String get netStatusGenericError => 'Something went wrong. Try again.';

  @override
  String get netStatusOffline => 'No internet connection';

  @override
  String get netStatusTimeout => 'Poor connection. Try again.';

  @override
  String get netStatusUnreachable => 'The server is not responding right now';

  @override
  String get notificationLogSheetArchived => '· archived';

  @override
  String get notificationLogSheetEmptyBody =>
      'Notifications are only sent for disruptions worth interrupting you for. If it is calm in your counties you hear nothing — and that is intended.';

  @override
  String get notificationLogSheetEmptyTitle => 'No notifications yet';

  @override
  String notificationLogSheetHoursAgo(int hours) {
    return '$hours h ago';
  }

  @override
  String get notificationLogSheetIntro =>
      'Notifications sent to this phone. Want to save a tip? Use the star in the tip list — it then stays under Saved for seven days.';

  @override
  String notificationLogSheetMinAgo(int minutes) {
    return '$minutes min ago';
  }

  @override
  String get notificationLogSheetNeedsBackend =>
      'Notification history needs a backend';

  @override
  String get notificationLogSheetNoPhone => 'No paired phone';

  @override
  String get notificationLogSheetNoPhoneBody =>
      'Notifications are sent to a paired device. This login has none.';

  @override
  String get notificationLogSheetNow => 'Just now';

  @override
  String get notificationLogSheetTitle => 'My notifications';

  @override
  String notifyPrefsAreaLine(String counties) {
    return 'Driving area: $counties';
  }

  @override
  String get notifyPrefsByArea => 'By your driving area';

  @override
  String get notifyPrefsHowImportant => 'How important?';

  @override
  String get notifyPrefsLevelAll => 'All';

  @override
  String get notifyPrefsLevelMedium => 'Medium +';

  @override
  String get notifyPrefsLevelStrong => 'Strong';

  @override
  String get notifyPrefsMoreOptions => 'More options';

  @override
  String get notifyPrefsNeedsLocation =>
      'On duty needs location while the app is in use';

  @override
  String get notifyPrefsNoActiveSeat =>
      'No active seat on this device — the settings cannot be saved.';

  @override
  String get notifyPrefsOnAgain => 'Notifications are on again.';

  @override
  String get notifyPrefsOnDuty => 'On duty';

  @override
  String get notifyPrefsPause => 'Pause';

  @override
  String get notifyPrefsPause1h => '1 hr';

  @override
  String get notifyPrefsPause4h => '4 hr';

  @override
  String get notifyPrefsPauseTonight => 'Tonight';

  @override
  String notifyPrefsPausedUntilSnack(String time) {
    return 'Paused until $time.';
  }

  @override
  String notifyPrefsPausedUntilTitle(String time) {
    return 'Paused until $time';
  }

  @override
  String get notifyPrefsResume => 'Start again';

  @override
  String get notifyPrefsSaved => 'Saved';

  @override
  String get notifyPrefsSendNotifications => 'Send notifications';

  @override
  String get notifyPrefsTitle => 'Notifications';

  @override
  String notifyPrefsTomorrowAt(String time) {
    return 'tomorrow $time';
  }

  @override
  String get notifyPrefsWhichNotifications => 'Which notifications?';

  @override
  String get notifyPrefsWithinKm => 'Within 30 km of you';

  @override
  String get notifyRulesApiInvalidResponse =>
      'Invalid response from the server';

  @override
  String notifyRulesApiServerResponded(int status) {
    return 'The server responded $status';
  }

  @override
  String offlineBannerOffline(String at) {
    return 'Offline – showing latest tips from $at';
  }

  @override
  String get offlineBannerRetry => 'Try again';

  @override
  String offlineBannerTimeout(String at) {
    return 'Poor connection – showing tips from $at';
  }

  @override
  String offlineBannerUnreachable(String at) {
    return 'Server not responding – showing tips from $at';
  }

  @override
  String get onboardingScreenClose => 'Close';

  @override
  String get onboardingScreenColorsBody =>
      'These are tips, not bookings. You decide if it is worth going.';

  @override
  String get onboardingScreenColorsTitle =>
      'The colour shows how strong the tip is';

  @override
  String get onboardingScreenDone => 'Done';

  @override
  String get onboardingScreenFeedbackBody =>
      'Tap a tip and choose Got a fare or No customer. That makes the tips better for everyone.';

  @override
  String get onboardingScreenFeedbackTitle => 'Tell us how it went';

  @override
  String get onboardingScreenLevelMedium => 'Medium';

  @override
  String get onboardingScreenLevelMediumText =>
      'Could lead to rides. Keep an eye on it.';

  @override
  String get onboardingScreenLevelStrong => 'Strong';

  @override
  String get onboardingScreenLevelStrongText => 'Many may need a taxi.';

  @override
  String get onboardingScreenLevelWeak => 'Weak';

  @override
  String get onboardingScreenLevelWeakText =>
      'Good to know, rarely worth going.';

  @override
  String get onboardingScreenNext => 'Next';

  @override
  String get onboardingScreenNotifBody =>
      'Turn on notifications in Settings. Then we will tell you when a strong tip shows up near you.';

  @override
  String get onboardingScreenNotifTitle => 'Notifications';

  @override
  String onboardingScreenPageOf(int page, int total) {
    return 'Page $page of $total';
  }

  @override
  String get onboardingScreenSkip => 'Skip';

  @override
  String get onboardingScreenStartBody =>
      'Create a free account, or log in if you already have one. Then we will show you around the app.';

  @override
  String get onboardingScreenStartTitle => 'Get started';

  @override
  String get onboardingScreenTrafficBody =>
      'Cancelled trains, late flights, ferries and events that end. We show where people may need a taxi. These are tips, not bookings.';

  @override
  String get onboardingScreenTrafficTitle => 'Tips from the traffic';

  @override
  String get settingsScreenAboutTips => 'About the tips';

  @override
  String get settingsScreenAccountClosed => 'The account is closed.';

  @override
  String get settingsScreenAccountDescription =>
      'Log out if you stop driving or change phone.';

  @override
  String get settingsScreenAccountTitle => 'Account';

  @override
  String get settingsScreenCancel => 'Cancel';

  @override
  String get settingsScreenCloseAccountBody =>
      'The membership will not renew. A trial in progress will end. You can keep using the app until the period ends.';

  @override
  String get settingsScreenCloseAccountConfirm => 'Close';

  @override
  String get settingsScreenCloseAccountTitle => 'Close the company account?';

  @override
  String get settingsScreenCloseCompanyAccount => 'Close the company account';

  @override
  String get settingsScreenCompanyDescription =>
      'Manage the company account in the customer portal on the web.';

  @override
  String get settingsScreenCompanyTitle => 'Company';

  @override
  String get settingsScreenCountiesMany =>
      'Tips and notifications in your counties. Tap to choose which.';

  @override
  String get settingsScreenCountiesOne =>
      'Tips and notifications in this county.';

  @override
  String get settingsScreenDelete => 'Delete';

  @override
  String get settingsScreenDeleteBodyDriver =>
      'Your driver account is removed and the device is disconnected from your seat. Your manager can invite you again. This cannot be undone.';

  @override
  String get settingsScreenDeleteBodyOffice =>
      'Your account and login are removed for good. Devices you have driven with are disconnected from the membership.\n\nIf you are the only owner, the company is closed right away: the membership and any trial in progress end, the drivers stop getting tips and the company is archived. This cannot be undone.';

  @override
  String get settingsScreenDeleteFailedTitle => 'The account was not deleted';

  @override
  String get settingsScreenDeleteMyAccount => 'Delete my account';

  @override
  String get settingsScreenDeleteTitle => 'Delete your account?';

  @override
  String get settingsScreenDeleted => 'Your account is deleted.';

  @override
  String get settingsScreenHelpChat => 'Chat with us';

  @override
  String get settingsScreenHelpDescription =>
      'See how the app works, or write to us.';

  @override
  String get settingsScreenHelpHowDriver => 'Four short pages';

  @override
  String get settingsScreenHelpHowItWorks => 'How Taxi Tips works';

  @override
  String get settingsScreenHelpHowOffice => 'The trial, membership and drivers';

  @override
  String get settingsScreenHelpTitle => 'Help';

  @override
  String get settingsScreenHelpTour => 'Show the tour again';

  @override
  String get settingsScreenHelpTourSub =>
      'Shows where to tap on the home screen';

  @override
  String settingsScreenHelpUnread(int count) {
    String _temp0 = intl.Intl.pluralLogic(
      count,
      locale: localeName,
      other: '$count new replies',
      one: 'One new reply',
    );
    return '$_temp0';
  }

  @override
  String get settingsScreenLoginForSettings => 'Log in to see the settings.';

  @override
  String get settingsScreenLogout => 'Log out';

  @override
  String get settingsScreenMembershipDescription =>
      'The seat you drive with and the counties you get tips from.';

  @override
  String settingsScreenMembershipDescriptionCompany(String company) {
    return 'The seat you drive with and the counties you get tips from. Company: $company.';
  }

  @override
  String get settingsScreenMembershipTitle => 'Membership';

  @override
  String get settingsScreenNotifyAllCounties => 'All your counties';

  @override
  String get settingsScreenNotifyDescription =>
      'Choose when the phone should alert you about a strong tip.';

  @override
  String settingsScreenNotifyFilter(String counties) {
    return 'Filter: $counties';
  }

  @override
  String get settingsScreenNotifyTitle => 'Notifications';

  @override
  String get settingsScreenOk => 'OK';

  @override
  String get settingsScreenPrivacy => 'Data policy';

  @override
  String get settingsScreenSignedInAs => 'Signed in as';

  @override
  String get settingsScreenTerms => 'Terms';

  @override
  String get settingsScreenTitle => 'Settings';

  @override
  String get settingsScreenYourCounties => 'Your counties';

  @override
  String severityLabelsCancelledAt(String clock) {
    return 'Cancelled $clock';
  }

  @override
  String severityLabelsClockChange(String from, String to) {
    return '$from → $to';
  }

  @override
  String get severityLabelsCompensationBase =>
      'The traveller may get the taxi paid';

  @override
  String get severityLabelsCompensationMaybe => 'Taxi may be reimbursed';

  @override
  String severityLabelsCompensationSentenceUpTo(String amount, String per) {
    String _temp0 = intl.Intl.selectLogic(per, {
      'person': ' per traveller',
      'trip': ' per trip',
      'other': '',
    });
    return 'The traveller may get the taxi paid up to $amount kr$_temp0';
  }

  @override
  String severityLabelsCompensationUpTo(int amount, String per) {
    String _temp0 = intl.Intl.selectLogic(per, {
      'person': ' per traveller',
      'trip': ' per trip',
      'other': '',
    });
    return 'Taxi reimbursed · up to $amount kr$_temp0';
  }

  @override
  String get severityLabelsConfidenceHigh => 'High — clear in the source data';

  @override
  String get severityLabelsConfidenceLow =>
      'Low — uncertain reading of the source data';

  @override
  String get severityLabelsConfidenceMedium => 'Medium';

  @override
  String get severityLabelsDelayed => 'Delayed';

  @override
  String severityLabelsDelayedBy(String delay) {
    return 'Delayed $delay';
  }

  @override
  String get severityLabelsDeparted => 'has left';

  @override
  String get severityLabelsDepartsNow => 'departing now';

  @override
  String severityLabelsHours(int hours) {
    return '$hours h';
  }

  @override
  String severityLabelsHoursMinutes(int hours, int minutes) {
    return '$hours h $minutes min';
  }

  @override
  String severityLabelsIn(String time) {
    return 'in $time';
  }

  @override
  String severityLabelsMinutes(int minutes) {
    return '$minutes min';
  }

  @override
  String get severityLabelsModeBoat => 'Boat';

  @override
  String get severityLabelsModeBus => 'Bus';

  @override
  String get severityLabelsModeEvents => 'Events';

  @override
  String get severityLabelsModeFerries => 'Ferries';

  @override
  String get severityLabelsModeFlight => 'Flights';

  @override
  String get severityLabelsModeMetro => 'Metro';

  @override
  String get severityLabelsModeRoad => 'Road';

  @override
  String get severityLabelsModeTrain => 'Train';

  @override
  String get severityLabelsModeTram => 'Tram';

  @override
  String severityLabelsMonthShort(String m) {
    String _temp0 = intl.Intl.selectLogic(m, {
      'm1': 'Jan',
      'm2': 'Feb',
      'm3': 'Mar',
      'm4': 'Apr',
      'm5': 'May',
      'm6': 'Jun',
      'm7': 'Jul',
      'm8': 'Aug',
      'm9': 'Sep',
      'm10': 'Oct',
      'm11': 'Nov',
      'm12': 'Dec',
      'other': '',
    });
    return '$_temp0';
  }

  @override
  String get severityLabelsShortArrivalWave => 'Arrival wave';

  @override
  String get severityLabelsShortIgnore => 'Other';

  @override
  String get severityLabelsShortLastArrival => 'Last arrival';

  @override
  String get severityLabelsShortLineDelayed => 'Delay, line is running';

  @override
  String get severityLabelsShortLinePaused => 'Whole line stopped';

  @override
  String get severityLabelsShortRoadAccident => 'Accident/closure';

  @override
  String get severityLabelsShortRoadWork => 'Roadworks';

  @override
  String get severityLabelsShortRoadWorkQueue => 'Roadworks/queue';

  @override
  String get severityLabelsShortUnclassified => 'Uncertain assessment';

  @override
  String get severityLabelsShortVehicleCancelled =>
      'Single departure cancelled';

  @override
  String get severityLabelsShortVehicleDelayed => 'Single departure delayed';

  @override
  String get severityLabelsTierArrivalWave => 'Many flights landing at once';

  @override
  String get severityLabelsTierArrivalWaveFerry =>
      'Many ferries arriving at once';

  @override
  String get severityLabelsTierIgnore =>
      'Other – message from the transport company';

  @override
  String get severityLabelsTierLastArrival =>
      'Last plane — nothing else lands for several hours';

  @override
  String get severityLabelsTierLastArrivalFerry =>
      'Last ferry — nothing else arrives for several hours';

  @override
  String get severityLabelsTierLineDelayed => 'Delay on the line';

  @override
  String get severityLabelsTierLinePaused => 'The whole line is stopped';

  @override
  String get severityLabelsTierRoadAccident => 'Accident or closed road';

  @override
  String get severityLabelsTierRoadWork => 'Minor roadworks';

  @override
  String get severityLabelsTierRoadWorkQueue => 'Roadworks or queues';

  @override
  String get severityLabelsTierUnclassified =>
      'Disruption (uncertain classification)';

  @override
  String get severityLabelsTierVehicleCancelled => 'A departure is cancelled';

  @override
  String get severityLabelsTierVehicleDelayed => 'A departure is delayed';

  @override
  String get severityLabelsTipFallback => 'Tip';

  @override
  String severityLabelsTitleWithMode(String mode, String title) {
    return '$mode: $title';
  }

  @override
  String severityLabelsTowards(String destination) {
    return 'towards $destination';
  }

  @override
  String get severityLabelsWaitLast => 'Last departure from here';

  @override
  String severityLabelsWaitThere(String at, String gap) {
    return 'Next there$at, $gap later';
  }

  @override
  String severityLabelsWaitThereFirst(String at, String gap) {
    return 'Next there not until$at, $gap later';
  }

  @override
  String severityLabelsWaitTrip(String at, String gap) {
    return 'Next trip$at, $gap later';
  }

  @override
  String severityLabelsWaitTripFirst(String at, String gap) {
    return 'Next trip not until$at, $gap later';
  }

  @override
  String get signalCardDrive => 'Drive there';

  @override
  String get signalCardNoteBody =>
      'We read the traffic and show where people may need a taxi. You decide if it is worth going.';

  @override
  String get signalCardNoteLine =>
      'Tips from the traffic situation, no guarantee of a fare';

  @override
  String signalCardNoteMore(String title) {
    return '$title. Show more';
  }

  @override
  String get signalCardNoteOk => 'Got it';

  @override
  String get signalCardNoteTitle => 'Tips, not bookings';

  @override
  String get signalCardOver => 'Over';

  @override
  String get signalCardSave => 'Save this tip';

  @override
  String get signalCardTaxiPays => 'Taxi is paid for';

  @override
  String get signalCardUnsave => 'Remove from saved';

  @override
  String signalKindsAgoDays(int days) {
    return '$days d';
  }

  @override
  String get signalKindsAgoNow => 'Now';

  @override
  String get signalKindsCategoryEvent => 'Event';

  @override
  String get signalKindsCategoryFerry => 'Ferry';

  @override
  String get signalKindsCategoryFlight => 'Flights';

  @override
  String get signalKindsCategoryRoad => 'Road';

  @override
  String get signalKindsCategoryTransit => 'Train & bus';

  @override
  String signalKindsDistanceKm(String km) {
    return '$km km';
  }

  @override
  String signalKindsDistanceMeters(int meters) {
    return '$meters m';
  }

  @override
  String get signalKindsExplainEvent =>
      'Match, concert or something else. The crowd goes home at the same time.';

  @override
  String get signalKindsExplainFerry =>
      'Ferry coming in. People get off at the port.';

  @override
  String get signalKindsExplainFlight =>
      'Many flights landing, or the last flight. People need a taxi from the airport.';

  @override
  String get signalKindsExplainRoad =>
      'Traffic accident. Expect queues, or take another road.';

  @override
  String get signalKindsExplainTransit =>
      'Train, bus or metro is stopped or late. People need a taxi.';

  @override
  String signalKindsLongDayRelative(String relative, String weekday) {
    return '$relative, $weekday';
  }

  @override
  String get signalKindsMeaningHigh => 'Likely that people need a taxi here.';

  @override
  String get signalKindsMeaningLow => 'Probably few need a taxi here.';

  @override
  String get signalKindsMeaningMedium =>
      'May be worth watching. Keep an eye on it.';

  @override
  String signalKindsMonthLong(String m) {
    String _temp0 = intl.Intl.selectLogic(m, {
      'm1': 'January',
      'm2': 'February',
      'm3': 'March',
      'm4': 'April',
      'm5': 'May',
      'm6': 'June',
      'm7': 'July',
      'm8': 'August',
      'm9': 'September',
      'm10': 'October',
      'm11': 'November',
      'm12': 'December',
      'other': '',
    });
    return '$_temp0';
  }

  @override
  String get signalKindsRoadClosed => 'Road closed';

  @override
  String get signalKindsRoadHazard => 'Obstacle on the road';

  @override
  String get signalKindsRoadMajor => 'Major disruption';

  @override
  String get signalKindsToday => 'Today';

  @override
  String get signalKindsTomorrow => 'Tomorrow';

  @override
  String signalKindsWeekdayLong(String d) {
    String _temp0 = intl.Intl.selectLogic(d, {
      'd1': 'monday',
      'd2': 'tuesday',
      'd3': 'wednesday',
      'd4': 'thursday',
      'd5': 'friday',
      'd6': 'saturday',
      'd7': 'sunday',
      'other': '',
    });
    return '$_temp0';
  }

  @override
  String signalKindsWeekdayShort(String d) {
    String _temp0 = intl.Intl.selectLogic(d, {
      'd1': 'mon',
      'd2': 'tue',
      'd3': 'wed',
      'd4': 'thu',
      'd5': 'fri',
      'd6': 'sat',
      'd7': 'sun',
      'other': '',
    });
    return '$_temp0';
  }

  @override
  String get signalKindsWordAccident => 'Accident';

  @override
  String get signalKindsWordBig => 'Big';

  @override
  String get signalKindsWordMedium => 'Medium';

  @override
  String get signalKindsWordMiddle => 'Medium';

  @override
  String get signalKindsWordQueue => 'Queue';

  @override
  String get signalKindsWordSmall => 'Small';

  @override
  String get signalKindsWordStrong => 'Strong';

  @override
  String get signalKindsWordWeak => 'Weak';

  @override
  String get signalKindsWordWork => 'Roadwork';

  @override
  String get signalKindsYesterday => 'Yesterday';

  @override
  String signalMapCluster(int count) {
    String _temp0 = intl.Intl.pluralLogic(
      count,
      locale: localeName,
      other: '$count items here',
      one: '1 item here',
    );
    return '$_temp0';
  }

  @override
  String signalMapFerry(String name) {
    return 'Ferry $name';
  }

  @override
  String get signupScreenBack => 'Back';

  @override
  String get signupScreenCompanyHelp =>
      'You do not need an organisation number now.';

  @override
  String get signupScreenCompanyHint => 'For example Anna\'s Taxi';

  @override
  String get signupScreenCompanyLabel => 'Company name';

  @override
  String get signupScreenCompanyQuestion => 'What is the company called?';

  @override
  String get signupScreenCompanyText => 'With my own cars or drivers.';

  @override
  String get signupScreenCompanyTitle => 'I have a taxi company';

  @override
  String get signupScreenContinueBankId => 'Continue with BankID';

  @override
  String get signupScreenCreateAccount => 'Create the account';

  @override
  String get signupScreenDateInvalid =>
      'The personal ID number (personnummer) has a date that does not exist. Check the number.';

  @override
  String get signupScreenEmailHelp => 'You log in with it.';

  @override
  String get signupScreenEmailLabel => 'Email';

  @override
  String get signupScreenEmailQuestion => 'Your email';

  @override
  String get signupScreenHaveAccount => 'Already have an account? Log in';

  @override
  String get signupScreenKindQuestion => 'How do you drive?';

  @override
  String signupScreenKindQuestionNamed(String name) {
    return 'Hi $name! How do you drive?';
  }

  @override
  String get signupScreenLoginInstead => 'Log in instead';

  @override
  String get signupScreenNext => 'Next';

  @override
  String get signupScreenNotSure => 'Not sure? Choose \"I drive on my own\".';

  @override
  String get signupScreenPasswordLabel => 'Password';

  @override
  String get signupScreenPasswordMin => 'At least 8 characters';

  @override
  String get signupScreenPasswordQuestion => 'Choose a password';

  @override
  String get signupScreenPhoneLabel => 'Mobile';

  @override
  String get signupScreenPhoneQuestion => 'Your mobile number';

  @override
  String get signupScreenProblemChoose => 'Choose one of the options.';

  @override
  String get signupScreenProblemCompany => 'Enter the company name.';

  @override
  String get signupScreenProblemEmail =>
      'That does not look like an email address. Write for example name@gmail.com.';

  @override
  String get signupScreenProblemPassword =>
      'The password needs at least 8 characters.';

  @override
  String get signupScreenProblemPhone =>
      'That does not look like a mobile number. Write for example 070 123 45 67.';

  @override
  String get signupScreenSoloText => 'You do not need a company.';

  @override
  String get signupScreenSoloTitle => 'I drive on my own';

  @override
  String get signupScreenSomethingWrong => 'Something went wrong. Try again.';

  @override
  String signupScreenStepOf(int n, int total) {
    return 'Step $n of $total';
  }

  @override
  String get signupScreenTitle => 'Try free for one month';

  @override
  String get signupScreenUnder18 =>
      'A sole proprietorship must be registered by someone aged 18 or older. Check the number.';

  @override
  String get supportChatEmptyBody =>
      'Write your question below. You get a notification when we have replied.';

  @override
  String get supportChatEmptyTitle => 'How can we help?';

  @override
  String get supportChatHint => 'Write a message';

  @override
  String get supportChatLoadFailed =>
      'Could not load the chat. Check your connection.';

  @override
  String get supportChatRetry => 'Try again';

  @override
  String get supportChatSend => 'Send';

  @override
  String get supportChatSendFailed => 'The message was not sent. Try again.';

  @override
  String get supportChatSubtitle => 'We reply as soon as we can';

  @override
  String get supportChatTitle => 'Support';

  @override
  String get tipDetailPartsChipCancelled => 'CANCELLED';

  @override
  String get tipDetailPartsChipDelayed => 'DELAYED';

  @override
  String tipDetailPartsChipDelayedBy(String delay) {
    return 'DELAYED $delay';
  }

  @override
  String tipDetailPartsNewClock(String clock) {
    return '→ $clock';
  }

  @override
  String get tipReportCancel => 'Cancel';

  @override
  String get tipReportFailed => 'Could not send the report. Try again.';

  @override
  String get tipReportHint => 'Optional explanation';

  @override
  String get tipReportIntro =>
      'Tell us briefly what is wrong, for example the wrong place or a problem that is already fixed.';

  @override
  String get tipReportReceived => 'Report received — thank you.';

  @override
  String get tipReportSend => 'Send report';

  @override
  String get tipReportThanks => 'Thanks — we will check the tip.';

  @override
  String get tipReportTitle => 'Report a wrong tip';

  @override
  String tipSheetAffectedParty(String party) {
    return 'Responsible party: $party';
  }

  @override
  String get tipSheetAlternativeTraffic => 'Alternative transport';

  @override
  String get tipSheetCircumstances => 'Special circumstances';

  @override
  String tipSheetClockAt(String clock) {
    return 'at $clock';
  }

  @override
  String get tipSheetClose => 'Close';

  @override
  String get tipSheetCompensationDisclaimer =>
      'The amount applies when the transport company\'s conditions are met. We cannot judge the individual trip.';

  @override
  String tipSheetCompensationLink(String operator) {
    return 'Read the rules at $operator';
  }

  @override
  String get tipSheetCompensationTitle => 'Taxi compensation';

  @override
  String get tipSheetDriveThere => 'Drive there';

  @override
  String get tipSheetEnded => 'Ended';

  @override
  String tipSheetEndedAgo(String span) {
    return 'Ended $span ago';
  }

  @override
  String get tipSheetEndedBanner => 'Ended. The tip is no longer valid.';

  @override
  String get tipSheetEndedJustNow => 'Ended just now';

  @override
  String get tipSheetGotFare => 'Got a fare';

  @override
  String get tipSheetHide => 'Hide';

  @override
  String tipSheetLineTo(String line, String to) {
    return '$line → $to';
  }

  @override
  String get tipSheetMinorNote =>
      'General message. We do not judge whether it is worth driving there.';

  @override
  String get tipSheetNavFailed => 'Could not open navigation.';

  @override
  String get tipSheetNoCustomer => 'No customer';

  @override
  String get tipSheetNoDescription => 'No further description available.';

  @override
  String get tipSheetOpenNavigation => 'Open navigation';

  @override
  String get tipSheetOperatorFallback => 'the transport company';

  @override
  String get tipSheetReadMore => 'Read more';

  @override
  String get tipSheetReported => 'Reported';

  @override
  String get tipSheetRoadAdvice => 'Expect queues, or choose another road.';

  @override
  String get tipSheetSave => 'Save the tip';

  @override
  String get tipSheetSectionEvent => 'Event & description';

  @override
  String get tipSheetSectionNotice => 'Transport company\'s message';

  @override
  String get tipSheetSectionRoad => 'The road there';

  @override
  String get tipSheetShowAllReasons => 'Show all reasons';

  @override
  String get tipSheetShowFewerReasons => 'Show fewer reasons';

  @override
  String get tipSheetShowFullText => 'Show full text';

  @override
  String get tipSheetShowLess => 'Show less';

  @override
  String get tipSheetSourcePage => 'Transport company\'s page';

  @override
  String tipSheetStartedAgo(String span) {
    return 'Started $span ago';
  }

  @override
  String get tipSheetStartedJustNow => 'Just started';

  @override
  String tipSheetStartsIn(String span) {
    return 'Starts in $span';
  }

  @override
  String get tipSheetStartsNow => 'Starts now';

  @override
  String get tipSheetStatusNotice => 'NOTICE';

  @override
  String get tipSheetStatusStopped => 'TRAFFIC STOPPED';

  @override
  String get tipSheetTaxiPaid => 'Taxi is paid';

  @override
  String get tipSheetUnsave => 'Remove from saved';

  @override
  String get trialWelcomeAllIncluded => 'Everything is included right now.';

  @override
  String get trialWelcomeClose => 'Close';

  @override
  String get trialWelcomeColorNote =>
      'The colour shows how strong the signal is. A strong signal means many people likely need a taxi.';

  @override
  String get trialWelcomeCostsNothing => 'It costs nothing to try.';

  @override
  String trialWelcomeDate(int day, String month) {
    String _temp0 = intl.Intl.selectLogic(month, {
      '1': 'January',
      '2': 'February',
      '3': 'March',
      '4': 'April',
      '5': 'May',
      '6': 'June',
      '7': 'July',
      '8': 'August',
      '9': 'September',
      '10': 'October',
      '11': 'November',
      '12': 'December',
      'other': '',
    });
    return '$_temp0 $day';
  }

  @override
  String get trialWelcomeDone => 'Done';

  @override
  String trialWelcomeFreeDays(int days) {
    String _temp0 = intl.Intl.pluralLogic(
      days,
      locale: localeName,
      other: 'Free for $days days.',
      one: 'Free for $days day.',
    );
    return '$_temp0';
  }

  @override
  String get trialWelcomeFreeToTry => 'Free to try.';

  @override
  String trialWelcomeFreeUntil(String date) {
    return 'Free until $date.';
  }

  @override
  String get trialWelcomeIncludedHeading => 'Included in the trial';

  @override
  String get trialWelcomeIncludedTitle => 'What is included in the trial?';

  @override
  String get trialWelcomeIncludedUnknown =>
      'You can see what is included in the trial in the app. What is not included has a lock.';

  @override
  String get trialWelcomeLineEvent =>
      'Events that end: a match, a concert or something else.';

  @override
  String get trialWelcomeLineFerry => 'Ferries docking at the harbour.';

  @override
  String get trialWelcomeLineFlight =>
      'Flights that are late, or when many flights land.';

  @override
  String get trialWelcomeLineRoad => 'Traffic accidents that stop the traffic.';

  @override
  String get trialWelcomeLineTransit =>
      'Trains and buses that are late or cancelled. The last departure.';

  @override
  String trialWelcomeNeedsMembership(String onWeb) {
    return 'That requires a membership. $onWeb';
  }

  @override
  String get trialWelcomeNext => 'Next';

  @override
  String get trialWelcomeOneSeat =>
      'You can have 1 spot in the trial, with one county.';

  @override
  String trialWelcomePageOf(int page, int total) {
    return 'Page $page of $total';
  }

  @override
  String get trialWelcomeReadyTitle => 'All set! You are up and running';

  @override
  String trialWelcomeSeats(int limit) {
    String _temp0 = intl.Intl.pluralLogic(
      limit,
      locale: localeName,
      other: 'You can have up to $limit spots in the trial.',
    );
    return '$_temp0';
  }

  @override
  String get trialWelcomeShowTips => 'Show the tips';

  @override
  String get trialWelcomeSkip => 'Skip';

  @override
  String get trialWelcomeStep1Text =>
      'Open Settings and tap Your counties. The county decides which tips you get.';

  @override
  String get trialWelcomeStep1Title => 'Change county';

  @override
  String get trialWelcomeStep2Text =>
      'The invitation is sent by the company\'s administrator on the web, not from the app. The driver gets an email, chooses a password and logs in to the app with email and password.';

  @override
  String get trialWelcomeStep2Title =>
      'Do you have a taxi company? Invite drivers on the web';

  @override
  String get trialWelcomeStepsTitle => 'How to get started';

  @override
  String trialWelcomeTrialEnded(String onWeb) {
    return 'The trial has ended. $onWeb';
  }

  @override
  String trialWelcomeTrialRunning(String date) {
    return 'The trial is running. It is valid until $date.';
  }

  @override
  String get trialWelcomeTrialStarts =>
      'The trial starts when the first driver logs in.';

  @override
  String get trialWelcomeTrialStartsPending =>
      'The trial starts when the first driver logs in. Until then no time passes.';

  @override
  String trialWelcomeTrialTitleDays(int days) {
    String _temp0 = intl.Intl.pluralLogic(
      days,
      locale: localeName,
      other: 'You are trying for free for $days days',
      one: 'You are trying for free for $days day',
    );
    return '$_temp0';
  }

  @override
  String get trialWelcomeTrialTitleNoDays => 'You are trying for free';

  @override
  String get trialWelcomeWatching => 'We watch';

  @override
  String get trialWelcomeWhatBody =>
      'Taxi Tips shows where people may need a taxi right now. These are tips, not promises. You decide if it is worth driving there.';

  @override
  String get trialWelcomeWhatTitle => 'Welcome to Taxi Tips';

  @override
  String get vehicleSessionAnotherPhone => 'another phone';

  @override
  String get vehicleSessionCancel => 'Cancel';

  @override
  String get vehicleSessionCar => 'Car';

  @override
  String vehicleSessionCountiesCount(int count) {
    String _temp0 = intl.Intl.pluralLogic(
      count,
      locale: localeName,
      other: '$count counties',
      one: '1 county',
    );
    return '$_temp0';
  }

  @override
  String get vehicleSessionDrive => 'Drive';

  @override
  String get vehicleSessionLeave => 'Leave the car';

  @override
  String get vehicleSessionNoVehicles =>
      'The phone is not connected to any car. Ask your manager to invite you with your email, and log in as a driver.';

  @override
  String get vehicleSessionSubtitle =>
      'Tips apply to the car\'s counties. A car can only have one phone at a time.';

  @override
  String get vehicleSessionTakeOver => 'Take over';

  @override
  String vehicleSessionTakeOverBody(String message) {
    return '$message\n\nThe other phone stops showing tips for this car right away.';
  }

  @override
  String get vehicleSessionTakeOverCar => 'Take over the car';

  @override
  String vehicleSessionTakeOverTitle(String plate) {
    return 'Take over $plate?';
  }

  @override
  String get vehicleSessionTheCar => 'the car';

  @override
  String get vehicleSessionTitle => 'Which car are you driving?';

  @override
  String vehicleSessionUsedBy(String name) {
    return 'Used by $name';
  }

  @override
  String get vehicleSessionYouDriveThis => 'You are driving this one';

  @override
  String get welcomeScreenBrowserFailed => 'Could not open the browser';

  @override
  String get welcomeScreenCreateAccount => 'Create a free account';

  @override
  String get welcomeScreenHeadline => 'See where people need a taxi';

  @override
  String get welcomeScreenLogin => 'Log in';

  @override
  String get welcomeScreenSeeDemo => 'See the demo on the web';
}
