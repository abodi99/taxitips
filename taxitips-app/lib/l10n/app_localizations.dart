import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter/widgets.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:intl/intl.dart' as intl;

import 'app_localizations_ar.dart';
import 'app_localizations_en.dart';
import 'app_localizations_sv.dart';

// ignore_for_file: type=lint

/// Callers can lookup localized strings with an instance of AppLocalizations
/// returned by `AppLocalizations.of(context)`.
///
/// Applications need to include `AppLocalizations.delegate()` in their app's
/// `localizationDelegates` list, and the locales they support in the app's
/// `supportedLocales` list. For example:
///
/// ```dart
/// import 'l10n/app_localizations.dart';
///
/// return MaterialApp(
///   localizationsDelegates: AppLocalizations.localizationsDelegates,
///   supportedLocales: AppLocalizations.supportedLocales,
///   home: MyApplicationHome(),
/// );
/// ```
///
/// ## Update pubspec.yaml
///
/// Please make sure to update your pubspec.yaml to include the following
/// packages:
///
/// ```yaml
/// dependencies:
///   # Internationalization support.
///   flutter_localizations:
///     sdk: flutter
///   intl: any # Use the pinned version from flutter_localizations
///
///   # Rest of dependencies
/// ```
///
/// ## iOS Applications
///
/// iOS applications define key application metadata, including supported
/// locales, in an Info.plist file that is built into the application bundle.
/// To configure the locales supported by your app, you’ll need to edit this
/// file.
///
/// First, open your project’s ios/Runner.xcworkspace Xcode workspace file.
/// Then, in the Project Navigator, open the Info.plist file under the Runner
/// project’s Runner folder.
///
/// Next, select the Information Property List item, select Add Item from the
/// Editor menu, then select Localizations from the pop-up menu.
///
/// Select and expand the newly-created Localizations item then, for each
/// locale your application supports, add a new item and select the locale
/// you wish to add from the pop-up menu in the Value field. This list should
/// be consistent with the languages listed in the AppLocalizations.supportedLocales
/// property.
abstract class AppLocalizations {
  AppLocalizations(String locale)
    : localeName = intl.Intl.canonicalizedLocale(locale.toString());

  final String localeName;

  static AppLocalizations of(BuildContext context) {
    return Localizations.of<AppLocalizations>(context, AppLocalizations)!;
  }

  static const LocalizationsDelegate<AppLocalizations> delegate =
      _AppLocalizationsDelegate();

  /// A list of this localizations delegate along with the default localizations
  /// delegates.
  ///
  /// Returns a list of localizations delegates containing this delegate along with
  /// GlobalMaterialLocalizations.delegate, GlobalCupertinoLocalizations.delegate,
  /// and GlobalWidgetsLocalizations.delegate.
  ///
  /// Additional delegates can be added by appending to this list in
  /// MaterialApp. This list does not have to be used at all if a custom list
  /// of delegates is preferred or required.
  static const List<LocalizationsDelegate<dynamic>> localizationsDelegates =
      <LocalizationsDelegate<dynamic>>[
        delegate,
        GlobalMaterialLocalizations.delegate,
        GlobalCupertinoLocalizations.delegate,
        GlobalWidgetsLocalizations.delegate,
      ];

  /// A list of this localizations delegate's supported locales.
  static const List<Locale> supportedLocales = <Locale>[
    Locale('ar'),
    Locale('en'),
    Locale('sv'),
  ];

  /// No description provided for @alertFeedbackGotFare.
  ///
  /// In sv, this message translates to:
  /// **'Fick körning'**
  String get alertFeedbackGotFare;

  /// No description provided for @alertFeedbackNoCustomer.
  ///
  /// In sv, this message translates to:
  /// **'Ingen kund'**
  String get alertFeedbackNoCustomer;

  /// No description provided for @alertFeedbackQueued.
  ///
  /// In sv, this message translates to:
  /// **'Sparat. Skickas när du har nät.'**
  String get alertFeedbackQueued;

  /// No description provided for @alertFeedbackSaveFailed.
  ///
  /// In sv, this message translates to:
  /// **'Kunde inte spara svaret. Försök igen.'**
  String get alertFeedbackSaveFailed;

  /// No description provided for @alertFeedbackThanks.
  ///
  /// In sv, this message translates to:
  /// **'Tack!'**
  String get alertFeedbackThanks;

  /// No description provided for @alertFeedbackTitle.
  ///
  /// In sv, this message translates to:
  /// **'Hur gick det?'**
  String get alertFeedbackTitle;

  /// No description provided for @apiClientAccountCreatedOffline.
  ///
  /// In sv, this message translates to:
  /// **'Kontot är skapat, men vi nådde inte servern. Logga in när du har nät igen.'**
  String get apiClientAccountCreatedOffline;

  /// No description provided for @apiClientAuthError.
  ///
  /// In sv, this message translates to:
  /// **'Auth-fel: {details}'**
  String apiClientAuthError(String details);

  /// No description provided for @apiClientBankIdUnavailable.
  ///
  /// In sv, this message translates to:
  /// **'BankID är inte tillgängligt just nu.'**
  String get apiClientBankIdUnavailable;

  /// Utvecklarfel: servern är inte konfigurerad
  ///
  /// In sv, this message translates to:
  /// **'API_BASE_URL är inte satt. Parkoppling och bilval kräver TaxiTips-backenden.'**
  String get apiClientBaseUrlMissing;

  /// No description provided for @apiClientCannotDeleteAccount.
  ///
  /// In sv, this message translates to:
  /// **'Det går inte att radera kontot just nu. Försök igen senare.'**
  String get apiClientCannotDeleteAccount;

  /// No description provided for @apiClientCouldNotCreateAccount.
  ///
  /// In sv, this message translates to:
  /// **'Kunde inte skapa konto'**
  String get apiClientCouldNotCreateAccount;

  /// No description provided for @apiClientDatabaseError.
  ///
  /// In sv, this message translates to:
  /// **'Databasfel: {details}'**
  String apiClientDatabaseError(String details);

  /// No description provided for @apiClientFavoritesNeedBackend.
  ///
  /// In sv, this message translates to:
  /// **'Favoriter kräver Django-backenden'**
  String get apiClientFavoritesNeedBackend;

  /// No description provided for @apiClientInvalidTransferCode.
  ///
  /// In sv, this message translates to:
  /// **'Ogiltig byteskod'**
  String get apiClientInvalidTransferCode;

  /// No description provided for @apiClientInvalidVerificationCode.
  ///
  /// In sv, this message translates to:
  /// **'Verifieringskoden är ogiltig'**
  String get apiClientInvalidVerificationCode;

  /// No description provided for @apiClientLoginFailed.
  ///
  /// In sv, this message translates to:
  /// **'Det gick inte att logga in. Försök igen.'**
  String get apiClientLoginFailed;

  /// No description provided for @apiClientLoginRequired.
  ///
  /// In sv, this message translates to:
  /// **'Logga in för att fortsätta.'**
  String get apiClientLoginRequired;

  /// No description provided for @apiClientNoCompany.
  ///
  /// In sv, this message translates to:
  /// **'Inget bolag'**
  String get apiClientNoCompany;

  /// No description provided for @apiClientNoDevice.
  ///
  /// In sv, this message translates to:
  /// **'Ingen enhet'**
  String get apiClientNoDevice;

  /// No description provided for @apiClientNoDeviceKey.
  ///
  /// In sv, this message translates to:
  /// **'Servern gav ingen enhetsnyckel.'**
  String get apiClientNoDeviceKey;

  /// No description provided for @apiClientNoDevicePush.
  ///
  /// In sv, this message translates to:
  /// **'Ingen enhet — logga in via backend för push'**
  String get apiClientNoDevicePush;

  /// No description provided for @apiClientNoDeviceToName.
  ///
  /// In sv, this message translates to:
  /// **'Ingen enhet att namnge.'**
  String get apiClientNoDeviceToName;

  /// No description provided for @apiClientNoValidSession.
  ///
  /// In sv, this message translates to:
  /// **'Inloggningen gav ingen giltig session.'**
  String get apiClientNoValidSession;

  /// No description provided for @apiClientNotLoggedIn.
  ///
  /// In sv, this message translates to:
  /// **'Inte inloggad'**
  String get apiClientNotLoggedIn;

  /// No description provided for @apiClientNotifyLineDelayedHelp.
  ///
  /// In sv, this message translates to:
  /// **'Vanligtvis en svag signal -- av som standard.'**
  String get apiClientNotifyLineDelayedHelp;

  /// No description provided for @apiClientNotifyLineDelayedLabel.
  ///
  /// In sv, this message translates to:
  /// **'Förseningar'**
  String get apiClientNotifyLineDelayedLabel;

  /// No description provided for @apiClientNotifyLineDelayedShort.
  ///
  /// In sv, this message translates to:
  /// **'Linjen kör, men försenad'**
  String get apiClientNotifyLineDelayedShort;

  /// No description provided for @apiClientNotifyLinePausedHelp.
  ///
  /// In sv, this message translates to:
  /// **'Störst chans att det finns folk som behöver taxi.'**
  String get apiClientNotifyLinePausedHelp;

  /// No description provided for @apiClientNotifyLinePausedLabel.
  ///
  /// In sv, this message translates to:
  /// **'Hela linjen står stilla'**
  String get apiClientNotifyLinePausedLabel;

  /// No description provided for @apiClientNotifyLinePausedShort.
  ///
  /// In sv, this message translates to:
  /// **'Ingen trafik alls på linjen'**
  String get apiClientNotifyLinePausedShort;

  /// No description provided for @apiClientNotifyNeedsServer.
  ///
  /// In sv, this message translates to:
  /// **'Notisvalen kräver TaxiTips-servern.'**
  String get apiClientNotifyNeedsServer;

  /// No description provided for @apiClientNotifyRoadAccidentHelp.
  ///
  /// In sv, this message translates to:
  /// **'Påverkar mest bilister redan på väg, men värt att veta om.'**
  String get apiClientNotifyRoadAccidentHelp;

  /// No description provided for @apiClientNotifyRoadAccidentLabel.
  ///
  /// In sv, this message translates to:
  /// **'Olycka eller avstängd väg'**
  String get apiClientNotifyRoadAccidentLabel;

  /// No description provided for @apiClientNotifyRoadShort.
  ///
  /// In sv, this message translates to:
  /// **'Vägtrafik'**
  String get apiClientNotifyRoadShort;

  /// No description provided for @apiClientNotifyRoadWorkHelp.
  ///
  /// In sv, this message translates to:
  /// **'Sällan en taxisignal -- av som standard.'**
  String get apiClientNotifyRoadWorkHelp;

  /// No description provided for @apiClientNotifyRoadWorkLabel.
  ///
  /// In sv, this message translates to:
  /// **'Vägarbete eller köbildning'**
  String get apiClientNotifyRoadWorkLabel;

  /// No description provided for @apiClientNotifyVehicleCancelledHelp.
  ///
  /// In sv, this message translates to:
  /// **'Färre påverkade, men kan ändå vara värt en titt.'**
  String get apiClientNotifyVehicleCancelledHelp;

  /// No description provided for @apiClientNotifyVehicleCancelledLabel.
  ///
  /// In sv, this message translates to:
  /// **'Enstaka avgång inställd'**
  String get apiClientNotifyVehicleCancelledLabel;

  /// No description provided for @apiClientNotifyVehicleCancelledShort.
  ///
  /// In sv, this message translates to:
  /// **'En avgång inställd, andra går som vanligt'**
  String get apiClientNotifyVehicleCancelledShort;

  /// No description provided for @apiClientOnDutyNeedsBackend.
  ///
  /// In sv, this message translates to:
  /// **'I tjänst kräver den nya backenden'**
  String get apiClientOnDutyNeedsBackend;

  /// No description provided for @apiClientPhoneNotPaired.
  ///
  /// In sv, this message translates to:
  /// **'Telefonen är inte parkopplad.'**
  String get apiClientPhoneNotPaired;

  /// No description provided for @apiClientSupportChatUnavailable.
  ///
  /// In sv, this message translates to:
  /// **'Supportchatten är inte tillgänglig här.'**
  String get apiClientSupportChatUnavailable;

  /// No description provided for @appMainLogout.
  ///
  /// In sv, this message translates to:
  /// **'Logga ut'**
  String get appMainLogout;

  /// No description provided for @appMainSomethingWrong.
  ///
  /// In sv, this message translates to:
  /// **'Något gick fel.'**
  String get appMainSomethingWrong;

  /// No description provided for @appMainTrialNotStarted.
  ///
  /// In sv, this message translates to:
  /// **'Kontot är skapat men provet kunde inte starta. Kontakta TaxiTips.'**
  String get appMainTrialNotStarted;

  /// No description provided for @appMainTryAgain.
  ///
  /// In sv, this message translates to:
  /// **'Försök igen'**
  String get appMainTryAgain;

  /// No description provided for @bankIdFlowAppNotFound.
  ///
  /// In sv, this message translates to:
  /// **'Vi hittar inte BankID-appen på den här telefonen. Skanna koden med BankID på en annan telefon.'**
  String get bankIdFlowAppNotFound;

  /// No description provided for @bankIdFlowApproveInApp.
  ///
  /// In sv, this message translates to:
  /// **'Godkänn i BankID-appen. Kom sedan tillbaka hit.'**
  String get bankIdFlowApproveInApp;

  /// No description provided for @bankIdFlowBadEmail.
  ///
  /// In sv, this message translates to:
  /// **'Fel e-post.'**
  String get bankIdFlowBadEmail;

  /// No description provided for @bankIdFlowCancel.
  ///
  /// In sv, this message translates to:
  /// **'Avbryt'**
  String get bankIdFlowCancel;

  /// No description provided for @bankIdFlowChangeEmail.
  ///
  /// In sv, this message translates to:
  /// **'Byt e-post också'**
  String get bankIdFlowChangeEmail;

  /// No description provided for @bankIdFlowFailed.
  ///
  /// In sv, this message translates to:
  /// **'Legitimeringen misslyckades. Försök igen.'**
  String get bankIdFlowFailed;

  /// No description provided for @bankIdFlowHello.
  ///
  /// In sv, this message translates to:
  /// **'Hej {name}!'**
  String bankIdFlowHello(String name);

  /// No description provided for @bankIdFlowHidePassword.
  ///
  /// In sv, this message translates to:
  /// **'Dölj lösenord'**
  String get bankIdFlowHidePassword;

  /// No description provided for @bankIdFlowNewEmail.
  ///
  /// In sv, this message translates to:
  /// **'Ny e-post'**
  String get bankIdFlowNewEmail;

  /// Dialogrubrik (utan namn) och fältetikett
  ///
  /// In sv, this message translates to:
  /// **'Nytt lösenord'**
  String get bankIdFlowNewPasswordTitle;

  /// No description provided for @bankIdFlowNoAccountHelp.
  ///
  /// In sv, this message translates to:
  /// **'Ditt BankID har inget konto här.\n\nFick du en inbjudan från ditt taxibolag? Be dem skicka inbjudan igen. Då får du ett mejl där du väljer ett nytt lösenord.\n\nHar du inget konto? Tryck på Skapa konto.'**
  String get bankIdFlowNoAccountHelp;

  /// No description provided for @bankIdFlowNoAccountTitle.
  ///
  /// In sv, this message translates to:
  /// **'Vi hittar inget konto'**
  String get bankIdFlowNoAccountTitle;

  /// No description provided for @bankIdFlowNoResponse.
  ///
  /// In sv, this message translates to:
  /// **'BankID svarar inte just nu. Försök igen.'**
  String get bankIdFlowNoResponse;

  /// No description provided for @bankIdFlowOk.
  ///
  /// In sv, this message translates to:
  /// **'OK'**
  String get bankIdFlowOk;

  /// No description provided for @bankIdFlowOpenBankId.
  ///
  /// In sv, this message translates to:
  /// **'Öppna BankID'**
  String get bankIdFlowOpenBankId;

  /// No description provided for @bankIdFlowOtherPhone.
  ///
  /// In sv, this message translates to:
  /// **'BankID på en annan telefon'**
  String get bankIdFlowOtherPhone;

  /// No description provided for @bankIdFlowPasswordHelper.
  ///
  /// In sv, this message translates to:
  /// **'Minst 8 tecken'**
  String get bankIdFlowPasswordHelper;

  /// No description provided for @bankIdFlowPasswordMin.
  ///
  /// In sv, this message translates to:
  /// **'Lösenordet: minst 8 tecken.'**
  String get bankIdFlowPasswordMin;

  /// No description provided for @bankIdFlowQrLabel.
  ///
  /// In sv, this message translates to:
  /// **'QR-kod för BankID'**
  String get bankIdFlowQrLabel;

  /// No description provided for @bankIdFlowSave.
  ///
  /// In sv, this message translates to:
  /// **'Spara'**
  String get bankIdFlowSave;

  /// No description provided for @bankIdFlowScanOnOther.
  ///
  /// In sv, this message translates to:
  /// **'Öppna BankID på din andra telefon och skanna koden.'**
  String get bankIdFlowScanOnOther;

  /// No description provided for @bankIdFlowShowPassword.
  ///
  /// In sv, this message translates to:
  /// **'Visa lösenord'**
  String get bankIdFlowShowPassword;

  /// No description provided for @bankIdFlowSomethingWrong.
  ///
  /// In sv, this message translates to:
  /// **'Något gick fel. Försök igen.'**
  String get bankIdFlowSomethingWrong;

  /// No description provided for @bankIdFlowThisPhone.
  ///
  /// In sv, this message translates to:
  /// **'BankID på den här telefonen'**
  String get bankIdFlowThisPhone;

  /// No description provided for @bankIdFlowTooLong.
  ///
  /// In sv, this message translates to:
  /// **'Det tog för lång tid. Försök igen.'**
  String get bankIdFlowTooLong;

  /// No description provided for @bankIdFlowTryAgain.
  ///
  /// In sv, this message translates to:
  /// **'Försök igen'**
  String get bankIdFlowTryAgain;

  /// No description provided for @bankIdFlowYourAccount.
  ///
  /// In sv, this message translates to:
  /// **'Ditt konto:'**
  String get bankIdFlowYourAccount;

  /// No description provided for @categoryBarAll.
  ///
  /// In sv, this message translates to:
  /// **'Alla'**
  String get categoryBarAll;

  /// No description provided for @categoryBarSaved.
  ///
  /// In sv, this message translates to:
  /// **'Sparat'**
  String get categoryBarSaved;

  /// No description provided for @companySettingsActiveTitle.
  ///
  /// In sv, this message translates to:
  /// **'Aktivt'**
  String get companySettingsActiveTitle;

  /// No description provided for @companySettingsAdd.
  ///
  /// In sv, this message translates to:
  /// **'Lägg till'**
  String get companySettingsAdd;

  /// No description provided for @companySettingsAddCar.
  ///
  /// In sv, this message translates to:
  /// **'Lägg till bil'**
  String get companySettingsAddCar;

  /// No description provided for @companySettingsAlreadyConnected.
  ///
  /// In sv, this message translates to:
  /// **'Redan kopplad'**
  String get companySettingsAlreadyConnected;

  /// No description provided for @companySettingsBlock.
  ///
  /// In sv, this message translates to:
  /// **'Spärra'**
  String get companySettingsBlock;

  /// No description provided for @companySettingsBlockBody.
  ///
  /// In sv, this message translates to:
  /// **'Telefonen slutar visa tips direkt och lämnar bilen. Föraren behöver en ny inbjudan för att komma in igen.'**
  String get companySettingsBlockBody;

  /// No description provided for @companySettingsBlockPhone.
  ///
  /// In sv, this message translates to:
  /// **'Spärra telefonen'**
  String get companySettingsBlockPhone;

  /// No description provided for @companySettingsBlockTitle.
  ///
  /// In sv, this message translates to:
  /// **'Spärra {label}?'**
  String companySettingsBlockTitle(String label);

  /// No description provided for @companySettingsCancel.
  ///
  /// In sv, this message translates to:
  /// **'Avbryt'**
  String get companySettingsCancel;

  /// No description provided for @companySettingsCar.
  ///
  /// In sv, this message translates to:
  /// **'Bil'**
  String get companySettingsCar;

  /// No description provided for @companySettingsCarAdded.
  ///
  /// In sv, this message translates to:
  /// **'{plate} är tillagd'**
  String companySettingsCarAdded(String plate);

  /// No description provided for @companySettingsCarMissingOnLicense.
  ///
  /// In sv, this message translates to:
  /// **'Bilen saknas på licensen. Kontakta support.'**
  String get companySettingsCarMissingOnLicense;

  /// No description provided for @companySettingsCarRemoved.
  ///
  /// In sv, this message translates to:
  /// **'{plate} är borttagen'**
  String companySettingsCarRemoved(String plate);

  /// No description provided for @companySettingsCars.
  ///
  /// In sv, this message translates to:
  /// **'{used} av {limit, plural, =1{bil} other{bilar}}'**
  String companySettingsCars(int used, int limit);

  /// No description provided for @companySettingsCarsLabel.
  ///
  /// In sv, this message translates to:
  /// **'Bilar'**
  String get companySettingsCarsLabel;

  /// No description provided for @companySettingsChangeAgainNextMonth.
  ///
  /// In sv, this message translates to:
  /// **'{label}\nDu kan byta län igen nästa månad.'**
  String companySettingsChangeAgainNextMonth(String label);

  /// No description provided for @companySettingsChangeUsesOne.
  ///
  /// In sv, this message translates to:
  /// **'{label}. Ett byte använder ett av dem.'**
  String companySettingsChangeUsesOne(String label);

  /// No description provided for @companySettingsCouldNotReadCompany.
  ///
  /// In sv, this message translates to:
  /// **'Kunde inte läsa företaget.'**
  String get companySettingsCouldNotReadCompany;

  /// No description provided for @companySettingsCountyChangesLeft.
  ///
  /// In sv, this message translates to:
  /// **'Länbyten kvar den här månaden: {remaining} av {total}'**
  String companySettingsCountyChangesLeft(int remaining, int total);

  /// No description provided for @companySettingsCountyNotChangeable.
  ///
  /// In sv, this message translates to:
  /// **'Länet kan inte bytas i appen.'**
  String get companySettingsCountyNotChangeable;

  /// No description provided for @companySettingsCountyWhereCarDrives.
  ///
  /// In sv, this message translates to:
  /// **'Län där bilen kör'**
  String get companySettingsCountyWhereCarDrives;

  /// No description provided for @companySettingsDaysLeft.
  ///
  /// In sv, this message translates to:
  /// **'{days} dagar kvar'**
  String companySettingsDaysLeft(int days);

  /// No description provided for @companySettingsDriveMyself.
  ///
  /// In sv, this message translates to:
  /// **'Kör själv med den här telefonen'**
  String get companySettingsDriveMyself;

  /// No description provided for @companySettingsDriver.
  ///
  /// In sv, this message translates to:
  /// **'Förare'**
  String get companySettingsDriver;

  /// No description provided for @companySettingsDriverEmail.
  ///
  /// In sv, this message translates to:
  /// **'Förarens e-post'**
  String get companySettingsDriverEmail;

  /// No description provided for @companySettingsDriverEmailError.
  ///
  /// In sv, this message translates to:
  /// **'Skriv förarens e-post, t.ex. namn@exempel.se'**
  String get companySettingsDriverEmailError;

  /// No description provided for @companySettingsDriverName.
  ///
  /// In sv, this message translates to:
  /// **'Förarens namn'**
  String get companySettingsDriverName;

  /// No description provided for @companySettingsDriverNameOptional.
  ///
  /// In sv, this message translates to:
  /// **'Förarens namn (frivilligt)'**
  String get companySettingsDriverNameOptional;

  /// No description provided for @companySettingsDrivers.
  ///
  /// In sv, this message translates to:
  /// **'Förare'**
  String get companySettingsDrivers;

  /// No description provided for @companySettingsDriversCount.
  ///
  /// In sv, this message translates to:
  /// **'{count} förare'**
  String companySettingsDriversCount(int count);

  /// No description provided for @companySettingsDrivingBy.
  ///
  /// In sv, this message translates to:
  /// **'Kör: {name}'**
  String companySettingsDrivingBy(String name);

  /// No description provided for @companySettingsDrivingNow.
  ///
  /// In sv, this message translates to:
  /// **'Kör nu'**
  String get companySettingsDrivingNow;

  /// No description provided for @companySettingsGraceLine.
  ///
  /// In sv, this message translates to:
  /// **'Tipsen fungerar till {date}.'**
  String companySettingsGraceLine(String date);

  /// No description provided for @companySettingsGraceTitle.
  ///
  /// In sv, this message translates to:
  /// **'Medlemskap pausas snart'**
  String get companySettingsGraceTitle;

  /// No description provided for @companySettingsInviteByEmail.
  ///
  /// In sv, this message translates to:
  /// **'Bjud in förare med e-post'**
  String get companySettingsInviteByEmail;

  /// No description provided for @companySettingsInviteDriverBody.
  ///
  /// In sv, this message translates to:
  /// **'Föraren får ett mejl, väljer lösenord och loggar in i appen. Då kopplas telefonen till bilen.'**
  String get companySettingsInviteDriverBody;

  /// No description provided for @companySettingsInviteDriverTitle.
  ///
  /// In sv, this message translates to:
  /// **'Bjud in förare till {plate}'**
  String companySettingsInviteDriverTitle(String plate);

  /// No description provided for @companySettingsInviteExpired.
  ///
  /// In sv, this message translates to:
  /// **'Inbjudan har gått ut'**
  String get companySettingsInviteExpired;

  /// No description provided for @companySettingsInviteRemoved.
  ///
  /// In sv, this message translates to:
  /// **'Inbjudan är borttagen'**
  String get companySettingsInviteRemoved;

  /// No description provided for @companySettingsInviteResent.
  ///
  /// In sv, this message translates to:
  /// **'Inbjudan skickad igen till {email}'**
  String companySettingsInviteResent(String email);

  /// No description provided for @companySettingsInviteSent.
  ///
  /// In sv, this message translates to:
  /// **'Inbjudan skickad till {email}'**
  String companySettingsInviteSent(String email);

  /// No description provided for @companySettingsInvitedCount.
  ///
  /// In sv, this message translates to:
  /// **'{count} inbjuden'**
  String companySettingsInvitedCount(int count);

  /// No description provided for @companySettingsInvitedNotLoggedIn.
  ///
  /// In sv, this message translates to:
  /// **'Inbjuden · har inte loggat in än'**
  String get companySettingsInvitedNotLoggedIn;

  /// No description provided for @companySettingsLastDay.
  ///
  /// In sv, this message translates to:
  /// **'Sista dagen'**
  String get companySettingsLastDay;

  /// No description provided for @companySettingsLoadFailedPull.
  ///
  /// In sv, this message translates to:
  /// **'Kunde inte läsa företaget just nu. Dra ner för att försöka igen.'**
  String get companySettingsLoadFailedPull;

  /// Tolv förkortade månadsnamn, kommaseparerade, januari först. Används i datum som 5 jan 2027.
  ///
  /// In sv, this message translates to:
  /// **'jan,feb,mar,apr,maj,jun,jul,aug,sep,okt,nov,dec'**
  String get companySettingsMonthsShort;

  /// No description provided for @companySettingsMore.
  ///
  /// In sv, this message translates to:
  /// **'Mer'**
  String get companySettingsMore;

  /// No description provided for @companySettingsNameHint.
  ///
  /// In sv, this message translates to:
  /// **'t.ex. Anna'**
  String get companySettingsNameHint;

  /// No description provided for @companySettingsNoCars.
  ///
  /// In sv, this message translates to:
  /// **'Inga bilar'**
  String get companySettingsNoCars;

  /// No description provided for @companySettingsNoChangesLeft.
  ///
  /// In sv, this message translates to:
  /// **'Inga länbyten kvar den här månaden.'**
  String get companySettingsNoChangesLeft;

  /// No description provided for @companySettingsNoCounty.
  ///
  /// In sv, this message translates to:
  /// **'Inget län'**
  String get companySettingsNoCounty;

  /// No description provided for @companySettingsNoDriver.
  ///
  /// In sv, this message translates to:
  /// **'Ingen förare'**
  String get companySettingsNoDriver;

  /// No description provided for @companySettingsNoDriverConnected.
  ///
  /// In sv, this message translates to:
  /// **'Ingen förare kopplad'**
  String get companySettingsNoDriverConnected;

  /// No description provided for @companySettingsNowDrives.
  ///
  /// In sv, this message translates to:
  /// **'Den här telefonen kör nu {plate}'**
  String companySettingsNowDrives(String plate);

  /// No description provided for @companySettingsNowDrivesIn.
  ///
  /// In sv, this message translates to:
  /// **'{plate} kör nu i {county}'**
  String companySettingsNowDrivesIn(String plate, String county);

  /// No description provided for @companySettingsOnlyAdminChanges.
  ///
  /// In sv, this message translates to:
  /// **'Bara en administratör kan byta län.'**
  String get companySettingsOnlyAdminChanges;

  /// No description provided for @companySettingsPairedPickCar.
  ///
  /// In sv, this message translates to:
  /// **'Telefonen är kopplad till {plate}. Välj bilen i listan.'**
  String companySettingsPairedPickCar(String plate);

  /// No description provided for @companySettingsPausedTitle.
  ///
  /// In sv, this message translates to:
  /// **'Pausat'**
  String get companySettingsPausedTitle;

  /// No description provided for @companySettingsPhoneBlocked.
  ///
  /// In sv, this message translates to:
  /// **'Telefonen är spärrad'**
  String get companySettingsPhoneBlocked;

  /// No description provided for @companySettingsPlateLabel.
  ///
  /// In sv, this message translates to:
  /// **'Registreringsnummer'**
  String get companySettingsPlateLabel;

  /// No description provided for @companySettingsRemove.
  ///
  /// In sv, this message translates to:
  /// **'Ta bort'**
  String get companySettingsRemove;

  /// No description provided for @companySettingsRemoveCar.
  ///
  /// In sv, this message translates to:
  /// **'Ta bort bilen'**
  String get companySettingsRemoveCar;

  /// No description provided for @companySettingsRemoveCarBody.
  ///
  /// In sv, this message translates to:
  /// **'Förarna i bilen slutar få tips direkt. Platsen i provet blir ledig.'**
  String get companySettingsRemoveCarBody;

  /// No description provided for @companySettingsRemoveCarTitle.
  ///
  /// In sv, this message translates to:
  /// **'Ta bort {plate}?'**
  String companySettingsRemoveCarTitle(String plate);

  /// No description provided for @companySettingsRename.
  ///
  /// In sv, this message translates to:
  /// **'Byt namn'**
  String get companySettingsRename;

  /// No description provided for @companySettingsRenewsLine.
  ///
  /// In sv, this message translates to:
  /// **'Förnyas {date}'**
  String companySettingsRenewsLine(String date);

  /// No description provided for @companySettingsResendInvite.
  ///
  /// In sv, this message translates to:
  /// **'Skicka igen'**
  String get companySettingsResendInvite;

  /// No description provided for @companySettingsRetry.
  ///
  /// In sv, this message translates to:
  /// **'Försök igen'**
  String get companySettingsRetry;

  /// No description provided for @companySettingsRevokeBody.
  ///
  /// In sv, this message translates to:
  /// **'{email} kan inte längre använda inbjudan för att logga in.'**
  String companySettingsRevokeBody(String email);

  /// No description provided for @companySettingsRevokeInvite.
  ///
  /// In sv, this message translates to:
  /// **'Ta bort inbjudan'**
  String get companySettingsRevokeInvite;

  /// No description provided for @companySettingsRevokeTitle.
  ///
  /// In sv, this message translates to:
  /// **'Ta bort inbjudan?'**
  String get companySettingsRevokeTitle;

  /// No description provided for @companySettingsSave.
  ///
  /// In sv, this message translates to:
  /// **'Spara'**
  String get companySettingsSave;

  /// No description provided for @companySettingsSendInvite.
  ///
  /// In sv, this message translates to:
  /// **'Skicka inbjudan'**
  String get companySettingsSendInvite;

  /// No description provided for @companySettingsSuspendedLine.
  ///
  /// In sv, this message translates to:
  /// **'Kontakta oss i chatten.'**
  String get companySettingsSuspendedLine;

  /// No description provided for @companySettingsSuspendedTitle.
  ///
  /// In sv, this message translates to:
  /// **'Avstängt'**
  String get companySettingsSuspendedTitle;

  /// No description provided for @companySettingsTapToChangeCounty.
  ///
  /// In sv, this message translates to:
  /// **'Tryck för att byta län'**
  String get companySettingsTapToChangeCounty;

  /// No description provided for @companySettingsTheCar.
  ///
  /// In sv, this message translates to:
  /// **'bilen'**
  String get companySettingsTheCar;

  /// No description provided for @companySettingsThePhone.
  ///
  /// In sv, this message translates to:
  /// **'telefonen'**
  String get companySettingsThePhone;

  /// No description provided for @companySettingsThisPhone.
  ///
  /// In sv, this message translates to:
  /// **'Den här telefonen'**
  String get companySettingsThisPhone;

  /// No description provided for @companySettingsTipsPaused.
  ///
  /// In sv, this message translates to:
  /// **'Tipsen är pausade.'**
  String get companySettingsTipsPaused;

  /// No description provided for @companySettingsTrialAllIncluded.
  ///
  /// In sv, this message translates to:
  /// **'Allt i appen ingår under provet.'**
  String get companySettingsTrialAllIncluded;

  /// No description provided for @companySettingsTrialContinuesLine.
  ///
  /// In sv, this message translates to:
  /// **'Medlemskapet fortsätter efter provet · {until} · {cars}'**
  String companySettingsTrialContinuesLine(String until, String cars);

  /// No description provided for @companySettingsTrialEndedTitle.
  ///
  /// In sv, this message translates to:
  /// **'Provet är slut'**
  String get companySettingsTrialEndedTitle;

  /// No description provided for @companySettingsTrialLine.
  ///
  /// In sv, this message translates to:
  /// **'{until} · {cars}'**
  String companySettingsTrialLine(String until, String cars);

  /// No description provided for @companySettingsTrialLockedNotIncluded.
  ///
  /// In sv, this message translates to:
  /// **'Det som har ett lås i appen ingår inte i provet.'**
  String get companySettingsTrialLockedNotIncluded;

  /// No description provided for @companySettingsTrialPendingLine.
  ///
  /// In sv, this message translates to:
  /// **'Startar när första telefonen kopplas · {cars}'**
  String companySettingsTrialPendingLine(String cars);

  /// No description provided for @companySettingsTrialTitle.
  ///
  /// In sv, this message translates to:
  /// **'Provperiod'**
  String get companySettingsTrialTitle;

  /// No description provided for @companySettingsTrialUntil.
  ///
  /// In sv, this message translates to:
  /// **'Provet gäller till {date}.'**
  String companySettingsTrialUntil(String date);

  /// No description provided for @companySettingsWhereDoesCarDrive.
  ///
  /// In sv, this message translates to:
  /// **'Var kör bilen?'**
  String get companySettingsWhereDoesCarDrive;

  /// No description provided for @companySettingsYourCompany.
  ///
  /// In sv, this message translates to:
  /// **'Ditt företag'**
  String get companySettingsYourCompany;

  /// No description provided for @countyChecklistAllCounties.
  ///
  /// In sv, this message translates to:
  /// **'Du ser tips från alla län i medlemskapet. Bocka ur dem du inte vill se.'**
  String get countyChecklistAllCounties;

  /// No description provided for @countyChecklistChangeTrialCounty.
  ///
  /// In sv, this message translates to:
  /// **'Byt provets län'**
  String get countyChecklistChangeTrialCounty;

  /// No description provided for @countyChecklistDone.
  ///
  /// In sv, this message translates to:
  /// **'Klar'**
  String get countyChecklistDone;

  /// No description provided for @countyChecklistNoCounties.
  ///
  /// In sv, this message translates to:
  /// **'Medlemskapet har inga län än.'**
  String get countyChecklistNoCounties;

  /// No description provided for @countyChecklistSomeCounties.
  ///
  /// In sv, this message translates to:
  /// **'Du ser tips från {selected} av {total} län.'**
  String countyChecklistSomeCounties(int selected, int total);

  /// No description provided for @countyChecklistTitle.
  ///
  /// In sv, this message translates to:
  /// **'Dina län'**
  String get countyChecklistTitle;

  /// No description provided for @driverScreenAccessInactive.
  ///
  /// In sv, this message translates to:
  /// **'Åtkomsten är inte aktiv.'**
  String get driverScreenAccessInactive;

  /// No description provided for @driverScreenAllCountiesSelected.
  ///
  /// In sv, this message translates to:
  /// **'Alla dina län är valda. Bocka ur dem du inte vill se.'**
  String get driverScreenAllCountiesSelected;

  /// No description provided for @driverScreenAllTips.
  ///
  /// In sv, this message translates to:
  /// **'Alla tips'**
  String get driverScreenAllTips;

  /// No description provided for @driverScreenAllYourCounties.
  ///
  /// In sv, this message translates to:
  /// **'Alla dina län ({count})'**
  String driverScreenAllYourCounties(int count);

  /// No description provided for @driverScreenArea.
  ///
  /// In sv, this message translates to:
  /// **'Område'**
  String get driverScreenArea;

  /// No description provided for @driverScreenBack.
  ///
  /// In sv, this message translates to:
  /// **'Tillbaka'**
  String get driverScreenBack;

  /// No description provided for @driverScreenBlockedBody.
  ///
  /// In sv, this message translates to:
  /// **'Kontakta TaxiTips support.'**
  String get driverScreenBlockedBody;

  /// No description provided for @driverScreenBlockedTitle.
  ///
  /// In sv, this message translates to:
  /// **'Kontot är avstängt'**
  String get driverScreenBlockedTitle;

  /// No description provided for @driverScreenCalm.
  ///
  /// In sv, this message translates to:
  /// **'Lugnt just nu'**
  String get driverScreenCalm;

  /// No description provided for @driverScreenCancelled.
  ///
  /// In sv, this message translates to:
  /// **'Avbrutet'**
  String get driverScreenCancelled;

  /// No description provided for @driverScreenCategoryLocked.
  ///
  /// In sv, this message translates to:
  /// **'{category} ingår inte i provet'**
  String driverScreenCategoryLocked(String category);

  /// No description provided for @driverScreenChoose.
  ///
  /// In sv, this message translates to:
  /// **'Välj'**
  String get driverScreenChoose;

  /// No description provided for @driverScreenChooseAreaText.
  ///
  /// In sv, this message translates to:
  /// **'Välj ditt körområde för att se tips.'**
  String get driverScreenChooseAreaText;

  /// No description provided for @driverScreenChooseCar.
  ///
  /// In sv, this message translates to:
  /// **'Välj vilken bil du kör för att se tips.'**
  String get driverScreenChooseCar;

  /// No description provided for @driverScreenChooseCarAction.
  ///
  /// In sv, this message translates to:
  /// **'Välj bil'**
  String get driverScreenChooseCarAction;

  /// No description provided for @driverScreenChooseCarFirstCounties.
  ///
  /// In sv, this message translates to:
  /// **'Välj bil först. Då visas bilens län här.'**
  String get driverScreenChooseCarFirstCounties;

  /// No description provided for @driverScreenClear.
  ///
  /// In sv, this message translates to:
  /// **'Rensa'**
  String get driverScreenClear;

  /// No description provided for @driverScreenClearFilters.
  ///
  /// In sv, this message translates to:
  /// **'Rensa filter'**
  String get driverScreenClearFilters;

  /// No description provided for @driverScreenConnectingPhone.
  ///
  /// In sv, this message translates to:
  /// **'Kopplar telefon…'**
  String get driverScreenConnectingPhone;

  /// No description provided for @driverScreenCountiesAndMunicipalities.
  ///
  /// In sv, this message translates to:
  /// **'Län och kommuner'**
  String get driverScreenCountiesAndMunicipalities;

  /// No description provided for @driverScreenDayToday.
  ///
  /// In sv, this message translates to:
  /// **'I dag'**
  String get driverScreenDayToday;

  /// No description provided for @driverScreenDayTomorrow.
  ///
  /// In sv, this message translates to:
  /// **'I morgon'**
  String get driverScreenDayTomorrow;

  /// No description provided for @driverScreenDayWeekend.
  ///
  /// In sv, this message translates to:
  /// **'Helgen'**
  String get driverScreenDayWeekend;

  /// No description provided for @driverScreenDays.
  ///
  /// In sv, this message translates to:
  /// **'{count, plural, other{{count} dagar}}'**
  String driverScreenDays(int count);

  /// No description provided for @driverScreenDone.
  ///
  /// In sv, this message translates to:
  /// **'Klar'**
  String get driverScreenDone;

  /// No description provided for @driverScreenDrivingArea.
  ///
  /// In sv, this message translates to:
  /// **'Körområde'**
  String get driverScreenDrivingArea;

  /// No description provided for @driverScreenDrivingAreaText.
  ///
  /// In sv, this message translates to:
  /// **'Länen du kör i. Notiserna, och listan när appen inte har din plats, följer körområdet.'**
  String get driverScreenDrivingAreaText;

  /// No description provided for @driverScreenEvents.
  ///
  /// In sv, this message translates to:
  /// **'Event'**
  String get driverScreenEvents;

  /// No description provided for @driverScreenEventsFailed.
  ///
  /// In sv, this message translates to:
  /// **'Kan inte hämta event just nu.'**
  String get driverScreenEventsFailed;

  /// No description provided for @driverScreenEventsToday.
  ///
  /// In sv, this message translates to:
  /// **'Event i dag'**
  String get driverScreenEventsToday;

  /// No description provided for @driverScreenFerries.
  ///
  /// In sv, this message translates to:
  /// **'Färjor'**
  String get driverScreenFerries;

  /// No description provided for @driverScreenFetchingPosition.
  ///
  /// In sv, this message translates to:
  /// **'Hämtar position…'**
  String get driverScreenFetchingPosition;

  /// No description provided for @driverScreenFilter.
  ///
  /// In sv, this message translates to:
  /// **'Filter'**
  String get driverScreenFilter;

  /// No description provided for @driverScreenGpsOff.
  ///
  /// In sv, this message translates to:
  /// **'Slå på plats (GPS) i telefonens inställningar'**
  String get driverScreenGpsOff;

  /// No description provided for @driverScreenGpsTimeout.
  ///
  /// In sv, this message translates to:
  /// **'GPS tog för lång tid — försök utomhus eller igen'**
  String get driverScreenGpsTimeout;

  /// No description provided for @driverScreenGroupMedium.
  ///
  /// In sv, this message translates to:
  /// **'Medel'**
  String get driverScreenGroupMedium;

  /// No description provided for @driverScreenGroupOther.
  ///
  /// In sv, this message translates to:
  /// **'Övrigt'**
  String get driverScreenGroupOther;

  /// No description provided for @driverScreenGroupStrong.
  ///
  /// In sv, this message translates to:
  /// **'Starka'**
  String get driverScreenGroupStrong;

  /// No description provided for @driverScreenGroupTitle.
  ///
  /// In sv, this message translates to:
  /// **'{name} · {count}'**
  String driverScreenGroupTitle(String name, int count);

  /// No description provided for @driverScreenGroupWeak.
  ///
  /// In sv, this message translates to:
  /// **'Svaga'**
  String get driverScreenGroupWeak;

  /// No description provided for @driverScreenHidden.
  ///
  /// In sv, this message translates to:
  /// **'Dolt: {types}'**
  String driverScreenHidden(String types);

  /// No description provided for @driverScreenHiddenTiers.
  ///
  /// In sv, this message translates to:
  /// **'{count, plural, other{{count} störningstyper dolda}}'**
  String driverScreenHiddenTiers(int count);

  /// No description provided for @driverScreenHistory.
  ///
  /// In sv, this message translates to:
  /// **'Historik'**
  String get driverScreenHistory;

  /// No description provided for @driverScreenKm.
  ///
  /// In sv, this message translates to:
  /// **'{km} km'**
  String driverScreenKm(int km);

  /// No description provided for @driverScreenLegend.
  ///
  /// In sv, this message translates to:
  /// **'Vad betyder symbolerna?'**
  String get driverScreenLegend;

  /// No description provided for @driverScreenLocationAllow.
  ///
  /// In sv, this message translates to:
  /// **'Tillåt plats för TaxiTips i telefonens inställningar'**
  String get driverScreenLocationAllow;

  /// No description provided for @driverScreenLocationDenied.
  ///
  /// In sv, this message translates to:
  /// **'Platsbehörighet nekades'**
  String get driverScreenLocationDenied;

  /// No description provided for @driverScreenLocationTimeout.
  ///
  /// In sv, this message translates to:
  /// **'Plats tog för lång tid'**
  String get driverScreenLocationTimeout;

  /// No description provided for @driverScreenLockedCount.
  ///
  /// In sv, this message translates to:
  /// **'{count, plural, =1{Just nu finns 1 sådant tips i ditt område.} other{Just nu finns {count} sådana tips i ditt område.}}'**
  String driverScreenLockedCount(int count);

  /// No description provided for @driverScreenLoginInvalid.
  ///
  /// In sv, this message translates to:
  /// **'Inloggningen fungerar inte. Logga in igen.'**
  String get driverScreenLoginInvalid;

  /// No description provided for @driverScreenMoreDates.
  ///
  /// In sv, this message translates to:
  /// **'Fler datum'**
  String get driverScreenMoreDates;

  /// No description provided for @driverScreenMoreOptions.
  ///
  /// In sv, this message translates to:
  /// **'Fler val: dölj typer'**
  String get driverScreenMoreOptions;

  /// No description provided for @driverScreenMovedBody.
  ///
  /// In sv, this message translates to:
  /// **'Ditt konto används nu på en annan telefon. Logga in här igen om du vill flytta tillbaka. Telefonen går att byta en gång i månaden.'**
  String get driverScreenMovedBody;

  /// No description provided for @driverScreenMovedTitle.
  ///
  /// In sv, this message translates to:
  /// **'Inloggad på en annan telefon'**
  String get driverScreenMovedTitle;

  /// No description provided for @driverScreenMunicipalitiesChosen.
  ///
  /// In sv, this message translates to:
  /// **'{count, plural, other{{count} kommuner valda}}'**
  String driverScreenMunicipalitiesChosen(int count);

  /// No description provided for @driverScreenMyPosition.
  ///
  /// In sv, this message translates to:
  /// **'Min position'**
  String get driverScreenMyPosition;

  /// No description provided for @driverScreenNavFailed.
  ///
  /// In sv, this message translates to:
  /// **'Kunde inte öppna navigeringen.'**
  String get driverScreenNavFailed;

  /// No description provided for @driverScreenNearMe.
  ///
  /// In sv, this message translates to:
  /// **'Nära mig'**
  String get driverScreenNearMe;

  /// No description provided for @driverScreenNearYou.
  ///
  /// In sv, this message translates to:
  /// **'Nära dig'**
  String get driverScreenNearYou;

  /// No description provided for @driverScreenNearYou25.
  ///
  /// In sv, this message translates to:
  /// **'Nära dig (25 km)'**
  String get driverScreenNearYou25;

  /// No description provided for @driverScreenNeedsInternet.
  ///
  /// In sv, this message translates to:
  /// **'Kräver internet. Försök igen när du har nät.'**
  String get driverScreenNeedsInternet;

  /// No description provided for @driverScreenNoAccess.
  ///
  /// In sv, this message translates to:
  /// **'Telefonen har ingen åtkomst. Logga in igen, eller be din chef att bjuda in dig.'**
  String get driverScreenNoAccess;

  /// No description provided for @driverScreenNoCountiesYet.
  ///
  /// In sv, this message translates to:
  /// **'Inga län än. Välj bil först.'**
  String get driverScreenNoCountiesYet;

  /// No description provided for @driverScreenNoCounty.
  ///
  /// In sv, this message translates to:
  /// **'Inget län valt'**
  String get driverScreenNoCounty;

  /// No description provided for @driverScreenNoEventsDays.
  ///
  /// In sv, this message translates to:
  /// **'Inga event de här dagarna.'**
  String get driverScreenNoEventsDays;

  /// No description provided for @driverScreenNoEventsWithin.
  ///
  /// In sv, this message translates to:
  /// **'Inga event inom {km} km. Välj ett längre avstånd.'**
  String driverScreenNoEventsWithin(int km);

  /// No description provided for @driverScreenNoFerries.
  ///
  /// In sv, this message translates to:
  /// **'Inga färjor på väg in just nu.'**
  String get driverScreenNoFerries;

  /// No description provided for @driverScreenNoNewTips.
  ///
  /// In sv, this message translates to:
  /// **'Nya tips visas inte just nu. {web} Det är inte samma sak som \"inga störningar just nu\".'**
  String driverScreenNoNewTips(String web);

  /// No description provided for @driverScreenNoRoadAccidents.
  ///
  /// In sv, this message translates to:
  /// **'Inga trafikolyckor i ditt område just nu.'**
  String get driverScreenNoRoadAccidents;

  /// No description provided for @driverScreenNoTipsFilters.
  ///
  /// In sv, this message translates to:
  /// **'Inga tips med de här filtren.'**
  String get driverScreenNoTipsFilters;

  /// No description provided for @driverScreenNotUpdated.
  ///
  /// In sv, this message translates to:
  /// **'Inte uppdaterat sedan {time}'**
  String driverScreenNotUpdated(String time);

  /// No description provided for @driverScreenNothingSaved.
  ///
  /// In sv, this message translates to:
  /// **'Inget sparat än.\n\nTryck på ☆ på ett tips eller ett event. Tips sparas i sju dagar; event tills dagen efter.'**
  String get driverScreenNothingSaved;

  /// No description provided for @driverScreenNow.
  ///
  /// In sv, this message translates to:
  /// **'Nu'**
  String get driverScreenNow;

  /// No description provided for @driverScreenOnlyStrong.
  ///
  /// In sv, this message translates to:
  /// **'Bara starka'**
  String get driverScreenOnlyStrong;

  /// No description provided for @driverScreenOnlyStrongest.
  ///
  /// In sv, this message translates to:
  /// **'Bara starkast'**
  String get driverScreenOnlyStrongest;

  /// No description provided for @driverScreenOpenSettings.
  ///
  /// In sv, this message translates to:
  /// **'Öppna inställningar'**
  String get driverScreenOpenSettings;

  /// No description provided for @driverScreenPausedBody.
  ///
  /// In sv, this message translates to:
  /// **'{notice} Det är inte samma sak som \"inga störningar just nu\".'**
  String driverScreenPausedBody(String notice);

  /// No description provided for @driverScreenPausedTitle.
  ///
  /// In sv, this message translates to:
  /// **'Medlemskapet är pausat'**
  String get driverScreenPausedTitle;

  /// No description provided for @driverScreenPhonePaired.
  ///
  /// In sv, this message translates to:
  /// **'Telefon kopplad'**
  String get driverScreenPhonePaired;

  /// No description provided for @driverScreenPositionFailed.
  ///
  /// In sv, this message translates to:
  /// **'Kunde inte hämta din position'**
  String get driverScreenPositionFailed;

  /// No description provided for @driverScreenPositionFailedShort.
  ///
  /// In sv, this message translates to:
  /// **'Kunde inte hämta position'**
  String get driverScreenPositionFailedShort;

  /// No description provided for @driverScreenPresetAll.
  ///
  /// In sv, this message translates to:
  /// **'Alla'**
  String get driverScreenPresetAll;

  /// No description provided for @driverScreenPresetStrong.
  ///
  /// In sv, this message translates to:
  /// **'Starka'**
  String get driverScreenPresetStrong;

  /// No description provided for @driverScreenPresetStrongest.
  ///
  /// In sv, this message translates to:
  /// **'Starkast'**
  String get driverScreenPresetStrongest;

  /// No description provided for @driverScreenRecentlyOver.
  ///
  /// In sv, this message translates to:
  /// **'Nyss slut ({count})'**
  String driverScreenRecentlyOver(int count);

  /// No description provided for @driverScreenRemovedSnack.
  ///
  /// In sv, this message translates to:
  /// **'Borttaget från sparade.'**
  String get driverScreenRemovedSnack;

  /// No description provided for @driverScreenResetFilter.
  ///
  /// In sv, this message translates to:
  /// **'Återställ filter'**
  String get driverScreenResetFilter;

  /// No description provided for @driverScreenRoadOnly.
  ///
  /// In sv, this message translates to:
  /// **'Bara trafikolyckor. Vägarbeten och avstängningar visas inte.'**
  String get driverScreenRoadOnly;

  /// No description provided for @driverScreenSaveFailed.
  ///
  /// In sv, this message translates to:
  /// **'Kunde inte spara tipset'**
  String get driverScreenSaveFailed;

  /// No description provided for @driverScreenSaved.
  ///
  /// In sv, this message translates to:
  /// **'Sparat'**
  String get driverScreenSaved;

  /// No description provided for @driverScreenSavedSnack.
  ///
  /// In sv, this message translates to:
  /// **'Sparat. Syns under ⭐ Sparat i sju dagar.'**
  String get driverScreenSavedSnack;

  /// No description provided for @driverScreenSectionTips.
  ///
  /// In sv, this message translates to:
  /// **'Tips'**
  String get driverScreenSectionTips;

  /// No description provided for @driverScreenSeeSettings.
  ///
  /// In sv, this message translates to:
  /// **'Se inställningar'**
  String get driverScreenSeeSettings;

  /// No description provided for @driverScreenSettings.
  ///
  /// In sv, this message translates to:
  /// **'Inställningar'**
  String get driverScreenSettings;

  /// No description provided for @driverScreenSettingsNewReply.
  ///
  /// In sv, this message translates to:
  /// **'Inställningar – nytt svar från supporten'**
  String get driverScreenSettingsNewReply;

  /// No description provided for @driverScreenShow.
  ///
  /// In sv, this message translates to:
  /// **'Visa'**
  String get driverScreenShow;

  /// No description provided for @driverScreenShowAll.
  ///
  /// In sv, this message translates to:
  /// **'Visa allt'**
  String get driverScreenShowAll;

  /// No description provided for @driverScreenShowDistance.
  ///
  /// In sv, this message translates to:
  /// **'Visa avstånd'**
  String get driverScreenShowDistance;

  /// No description provided for @driverScreenShowFullList.
  ///
  /// In sv, this message translates to:
  /// **'Visa hela listan'**
  String get driverScreenShowFullList;

  /// No description provided for @driverScreenShowMap.
  ///
  /// In sv, this message translates to:
  /// **'Visa kartan'**
  String get driverScreenShowMap;

  /// No description provided for @driverScreenSort.
  ///
  /// In sv, this message translates to:
  /// **'Sortera'**
  String get driverScreenSort;

  /// No description provided for @driverScreenSortImportant.
  ///
  /// In sv, this message translates to:
  /// **'Viktigast'**
  String get driverScreenSortImportant;

  /// No description provided for @driverScreenSortNearest.
  ///
  /// In sv, this message translates to:
  /// **'Närmast'**
  String get driverScreenSortNearest;

  /// No description provided for @driverScreenSortNewest.
  ///
  /// In sv, this message translates to:
  /// **'Nyast'**
  String get driverScreenSortNewest;

  /// No description provided for @driverScreenStrength.
  ///
  /// In sv, this message translates to:
  /// **'Styrka'**
  String get driverScreenStrength;

  /// No description provided for @driverScreenStrengthRange.
  ///
  /// In sv, this message translates to:
  /// **'Styrka {min}–{max}'**
  String driverScreenStrengthRange(int min, int max);

  /// No description provided for @driverScreenTipGone.
  ///
  /// In sv, this message translates to:
  /// **'Tipset finns inte längre, eller så har bilen inte tillgång till det.'**
  String get driverScreenTipGone;

  /// No description provided for @driverScreenTipsPausedTitle.
  ///
  /// In sv, this message translates to:
  /// **'Tipsen är pausade'**
  String get driverScreenTipsPausedTitle;

  /// No description provided for @driverScreenTrialEndedTitle.
  ///
  /// In sv, this message translates to:
  /// **'Provperioden är slut'**
  String get driverScreenTrialEndedTitle;

  /// No description provided for @driverScreenTrialNotStartedBody.
  ///
  /// In sv, this message translates to:
  /// **'Välj län under Inställningar. Förare bjuds in på webben. Provperioden startar när den första föraren loggar in.'**
  String get driverScreenTrialNotStartedBody;

  /// No description provided for @driverScreenTrialNotStartedTitle.
  ///
  /// In sv, this message translates to:
  /// **'Välkommen! Ett steg kvar'**
  String get driverScreenTrialNotStartedTitle;

  /// No description provided for @driverScreenUnsaveFailed.
  ///
  /// In sv, this message translates to:
  /// **'Kunde inte ta bort tipset'**
  String get driverScreenUnsaveFailed;

  /// No description provided for @driverScreenWholeCounty.
  ///
  /// In sv, this message translates to:
  /// **'Hela länet · välj kommuner'**
  String get driverScreenWholeCounty;

  /// No description provided for @driverScreenWholeCountyShort.
  ///
  /// In sv, this message translates to:
  /// **'Hela länet'**
  String get driverScreenWholeCountyShort;

  /// No description provided for @driverScreenWithin25.
  ///
  /// In sv, this message translates to:
  /// **'Inom ca 25 km'**
  String get driverScreenWithin25;

  /// No description provided for @driverScreenYellowShown.
  ///
  /// In sv, this message translates to:
  /// **'Gul = visas. Tryck för att dölja.'**
  String get driverScreenYellowShown;

  /// No description provided for @driverScreenZoomIn.
  ///
  /// In sv, this message translates to:
  /// **'Zooma in'**
  String get driverScreenZoomIn;

  /// No description provided for @driverScreenZoomOut.
  ///
  /// In sv, this message translates to:
  /// **'Zooma ut'**
  String get driverScreenZoomOut;

  /// No description provided for @driverTourCategoriesText.
  ///
  /// In sv, this message translates to:
  /// **'Välj vad du vill se: tåg och buss, väg, flyg, färja eller event. Siffran är antal tips. Sparat visar tipsen du har sparat.'**
  String get driverTourCategoriesText;

  /// No description provided for @driverTourCategoriesTitle.
  ///
  /// In sv, this message translates to:
  /// **'Kategorier'**
  String get driverTourCategoriesTitle;

  /// No description provided for @driverTourDrive.
  ///
  /// In sv, this message translates to:
  /// **'Kör dit'**
  String get driverTourDrive;

  /// No description provided for @driverTourFilterText.
  ///
  /// In sv, this message translates to:
  /// **'Med Filter väljer du län, hur starka tips du vill se och vad som ska döljas. Välj ditt län här så får du tips därifrån.'**
  String get driverTourFilterText;

  /// No description provided for @driverTourFilterTitle.
  ///
  /// In sv, this message translates to:
  /// **'Filter och län'**
  String get driverTourFilterTitle;

  /// No description provided for @driverTourHowWasIt.
  ///
  /// In sv, this message translates to:
  /// **'Hur gick det?'**
  String get driverTourHowWasIt;

  /// No description provided for @driverTourListText.
  ///
  /// In sv, this message translates to:
  /// **'Här är tipsen nära dig. Det starkaste ligger överst. Dra listan uppåt för att se fler.'**
  String get driverTourListText;

  /// No description provided for @driverTourListTitle.
  ///
  /// In sv, this message translates to:
  /// **'Tipslistan'**
  String get driverTourListTitle;

  /// No description provided for @driverTourMapText.
  ///
  /// In sv, this message translates to:
  /// **'Varje nål är ett tips. Nålen har samma färg som tipset. Tryck på en nål för att öppna tipset. Överst förklarar frågetecknet symbolerna, och klockan i vänstra hörnet är Historik: tipsen från det senaste dygnet.'**
  String get driverTourMapText;

  /// No description provided for @driverTourMapTitle.
  ///
  /// In sv, this message translates to:
  /// **'Kartan och nålarna'**
  String get driverTourMapTitle;

  /// No description provided for @driverTourSave.
  ///
  /// In sv, this message translates to:
  /// **'Spara'**
  String get driverTourSave;

  /// No description provided for @driverTourSettingsDriver.
  ///
  /// In sv, this message translates to:
  /// **'Här slår du på notiser och väljer bilen du kör. Notiser säger till när ett starkt tips dyker upp nära dig. Genomgången finns kvar under Hjälp.'**
  String get driverTourSettingsDriver;

  /// No description provided for @driverTourSettingsOwner.
  ///
  /// In sv, this message translates to:
  /// **'Här väljer du län och slår på notiser. Förare bjuds in på webben. Här väljer du också vilken plats du kör med. Genomgången finns kvar under Hjälp.'**
  String get driverTourSettingsOwner;

  /// No description provided for @driverTourSettingsTitle.
  ///
  /// In sv, this message translates to:
  /// **'Inställningar'**
  String get driverTourSettingsTitle;

  /// No description provided for @driverTourStrengthText.
  ///
  /// In sv, this message translates to:
  /// **'Varje tips har en färg och ett ord. Längst ner i listan finns \"Övrigt\": meddelanden från trafikbolag. Det är information, inte tips.'**
  String get driverTourStrengthText;

  /// No description provided for @driverTourStrengthTitle.
  ///
  /// In sv, this message translates to:
  /// **'Färgen visar styrkan'**
  String get driverTourStrengthTitle;

  /// No description provided for @driverTourTipText.
  ///
  /// In sv, this message translates to:
  /// **'Då öppnas ett blad med mer om tipset. Där kan du köra dit, spara tipset och svara hur det gick. Svaren gör tipsen bättre.'**
  String get driverTourTipText;

  /// No description provided for @driverTourTipTitle.
  ///
  /// In sv, this message translates to:
  /// **'Tryck på ett tips'**
  String get driverTourTipTitle;

  /// No description provided for @eventsScreenAllCounties.
  ///
  /// In sv, this message translates to:
  /// **'Alla län'**
  String get eventsScreenAllCounties;

  /// No description provided for @eventsScreenAllKinds.
  ///
  /// In sv, this message translates to:
  /// **'Alla sorter'**
  String get eventsScreenAllKinds;

  /// No description provided for @eventsScreenCount.
  ///
  /// In sv, this message translates to:
  /// **'{count, plural, other{{count} evenemang}}'**
  String eventsScreenCount(int count);

  /// No description provided for @eventsScreenError.
  ///
  /// In sv, this message translates to:
  /// **'Kunde inte hämta evenemangen: {error}'**
  String eventsScreenError(String error);

  /// No description provided for @eventsScreenFollowing.
  ///
  /// In sv, this message translates to:
  /// **'Du följer eventet. Det finns under ⭐ Sparat på kartan.'**
  String get eventsScreenFollowing;

  /// No description provided for @eventsScreenLoading.
  ///
  /// In sv, this message translates to:
  /// **'Hämtar {period}…'**
  String eventsScreenLoading(String period);

  /// No description provided for @eventsScreenMonth.
  ///
  /// In sv, this message translates to:
  /// **'30 dagar'**
  String get eventsScreenMonth;

  /// No description provided for @eventsScreenNone.
  ///
  /// In sv, this message translates to:
  /// **'Inga evenemang {period} i ditt område.'**
  String eventsScreenNone(String period);

  /// No description provided for @eventsScreenNoneHint.
  ///
  /// In sv, this message translates to:
  /// **'Dagarna ovan har evenemang — tryck på en av dem, eller välj en längre period.'**
  String get eventsScreenNoneHint;

  /// No description provided for @eventsScreenNoneThin.
  ///
  /// In sv, this message translates to:
  /// **'Utbudet är tunt utanför storstäderna. Prova ett annat län.'**
  String get eventsScreenNoneThin;

  /// No description provided for @eventsScreenOtherKind.
  ///
  /// In sv, this message translates to:
  /// **'Övrigt'**
  String get eventsScreenOtherKind;

  /// No description provided for @eventsScreenPickDay.
  ///
  /// In sv, this message translates to:
  /// **'Välj dag'**
  String get eventsScreenPickDay;

  /// No description provided for @eventsScreenPickPeriod.
  ///
  /// In sv, this message translates to:
  /// **'Välj period'**
  String get eventsScreenPickPeriod;

  /// No description provided for @eventsScreenQuarter.
  ///
  /// In sv, this message translates to:
  /// **'3 månader'**
  String get eventsScreenQuarter;

  /// No description provided for @eventsScreenSortLargest.
  ///
  /// In sv, this message translates to:
  /// **'Störst'**
  String get eventsScreenSortLargest;

  /// No description provided for @eventsScreenSortNearest.
  ///
  /// In sv, this message translates to:
  /// **'Närmast'**
  String get eventsScreenSortNearest;

  /// No description provided for @eventsScreenSortTime.
  ///
  /// In sv, this message translates to:
  /// **'Tid'**
  String get eventsScreenSortTime;

  /// No description provided for @eventsScreenSummary.
  ///
  /// In sv, this message translates to:
  /// **'{count} · {period}'**
  String eventsScreenSummary(String count, String period);

  /// No description provided for @eventsScreenSummaryFiltered.
  ///
  /// In sv, this message translates to:
  /// **'{shown} av {total} evenemang · {period}'**
  String eventsScreenSummaryFiltered(int shown, int total, String period);

  /// No description provided for @eventsScreenTitle.
  ///
  /// In sv, this message translates to:
  /// **'Evenemang'**
  String get eventsScreenTitle;

  /// No description provided for @eventsScreenToday.
  ///
  /// In sv, this message translates to:
  /// **'I dag'**
  String get eventsScreenToday;

  /// No description provided for @eventsScreenTodayPrefix.
  ///
  /// In sv, this message translates to:
  /// **'I dag · '**
  String get eventsScreenTodayPrefix;

  /// No description provided for @eventsScreenTomorrow.
  ///
  /// In sv, this message translates to:
  /// **'I morgon'**
  String get eventsScreenTomorrow;

  /// No description provided for @eventsScreenTomorrowPrefix.
  ///
  /// In sv, this message translates to:
  /// **'I morgon · '**
  String get eventsScreenTomorrowPrefix;

  /// No description provided for @eventsScreenUnfollowed.
  ///
  /// In sv, this message translates to:
  /// **'Du följer det inte längre.'**
  String get eventsScreenUnfollowed;

  /// No description provided for @eventsScreenWeek.
  ///
  /// In sv, this message translates to:
  /// **'7 dagar'**
  String get eventsScreenWeek;

  /// No description provided for @eventsScreenWeekend.
  ///
  /// In sv, this message translates to:
  /// **'Helgen'**
  String get eventsScreenWeekend;

  /// No description provided for @eventsScreenWholeArea.
  ///
  /// In sv, this message translates to:
  /// **'Hela området'**
  String get eventsScreenWholeArea;

  /// No description provided for @ferryEventApproaching.
  ///
  /// In sv, this message translates to:
  /// **'På väg in'**
  String get ferryEventApproaching;

  /// No description provided for @ferryEventAtQuay.
  ///
  /// In sv, this message translates to:
  /// **'Vid kaj'**
  String get ferryEventAtQuay;

  /// No description provided for @ferryEventAtQuaySince.
  ///
  /// In sv, this message translates to:
  /// **'Vid kaj sedan {clock}'**
  String ferryEventAtQuaySince(String clock);

  /// No description provided for @ferryEventAtTime.
  ///
  /// In sv, this message translates to:
  /// **'Kl {time}'**
  String ferryEventAtTime(String time);

  /// No description provided for @ferryEventByTimetable.
  ///
  /// In sv, this message translates to:
  /// **'Enligt tidtabell'**
  String get ferryEventByTimetable;

  /// No description provided for @ferryEventConfirmed.
  ///
  /// In sv, this message translates to:
  /// **'Bekräftad'**
  String get ferryEventConfirmed;

  /// No description provided for @ferryEventConfirmedApproaching.
  ///
  /// In sv, this message translates to:
  /// **'Bekräftad – fartyget är på väg in'**
  String get ferryEventConfirmedApproaching;

  /// No description provided for @ferryEventConfirmedBerthed.
  ///
  /// In sv, this message translates to:
  /// **'Bekräftad – fartyget ligger vid kaj'**
  String get ferryEventConfirmedBerthed;

  /// No description provided for @ferryEventDistance.
  ///
  /// In sv, this message translates to:
  /// **'{distance} · ca {time} med bil'**
  String ferryEventDistance(String distance, String time);

  /// No description provided for @ferryEventDockingNow.
  ///
  /// In sv, this message translates to:
  /// **'Lägger till nu'**
  String get ferryEventDockingNow;

  /// No description provided for @ferryEventDocksAt.
  ///
  /// In sv, this message translates to:
  /// **'Lägger till {clock} · {relative}'**
  String ferryEventDocksAt(String clock, String relative);

  /// No description provided for @ferryEventEarly.
  ///
  /// In sv, this message translates to:
  /// **'{time} tidig'**
  String ferryEventEarly(String time);

  /// No description provided for @ferryEventEndEstimated.
  ///
  /// In sv, this message translates to:
  /// **'Sluttiden är uppskattad, inte angiven av arrangören.'**
  String get ferryEventEndEstimated;

  /// No description provided for @ferryEventEndsAbout.
  ///
  /// In sv, this message translates to:
  /// **'Slutar ca {time}'**
  String ferryEventEndsAbout(String time);

  /// No description provided for @ferryEventFerry.
  ///
  /// In sv, this message translates to:
  /// **'Färja'**
  String get ferryEventFerry;

  /// No description provided for @ferryEventFollow.
  ///
  /// In sv, this message translates to:
  /// **'Följ'**
  String get ferryEventFollow;

  /// No description provided for @ferryEventFollowing.
  ///
  /// In sv, this message translates to:
  /// **'Följer'**
  String get ferryEventFollowing;

  /// No description provided for @ferryEventFrom.
  ///
  /// In sv, this message translates to:
  /// **'Från {place}'**
  String ferryEventFrom(String place);

  /// No description provided for @ferryEventInternational.
  ///
  /// In sv, this message translates to:
  /// **'Utrikes'**
  String get ferryEventInternational;

  /// No description provided for @ferryEventLate.
  ///
  /// In sv, this message translates to:
  /// **'{time} sen'**
  String ferryEventLate(String time);

  /// No description provided for @ferryEventOnTime.
  ///
  /// In sv, this message translates to:
  /// **'I tid'**
  String get ferryEventOnTime;

  /// No description provided for @ferryEventOngoing.
  ///
  /// In sv, this message translates to:
  /// **'Pågår nu'**
  String get ferryEventOngoing;

  /// No description provided for @ferryEventOriginDeparted.
  ///
  /// In sv, this message translates to:
  /// **'{from}, avgick {clock}'**
  String ferryEventOriginDeparted(String from, String clock);

  /// No description provided for @ferryEventOriginDeparts.
  ///
  /// In sv, this message translates to:
  /// **'{from}, avgår {clock}'**
  String ferryEventOriginDeparts(String from, String clock);

  /// No description provided for @ferryEventPeopleLeave.
  ///
  /// In sv, this message translates to:
  /// **'Folk går till {time}'**
  String ferryEventPeopleLeave(String time);

  /// No description provided for @ferryEventPickupNow.
  ///
  /// In sv, this message translates to:
  /// **'Folk kommer ut nu, till {clock}'**
  String ferryEventPickupNow(String clock);

  /// No description provided for @ferryEventPickupRange.
  ///
  /// In sv, this message translates to:
  /// **'Folk kommer ut {range}'**
  String ferryEventPickupRange(String range);

  /// No description provided for @ferryEventPickupValueNow.
  ///
  /// In sv, this message translates to:
  /// **'nu, till {clock}'**
  String ferryEventPickupValueNow(String clock);

  /// No description provided for @ferryEventReachAfter.
  ///
  /// In sv, this message translates to:
  /// **'Framme ca {clock} – efter att de flesta gått'**
  String ferryEventReachAfter(String clock);

  /// No description provided for @ferryEventReachBefore.
  ///
  /// In sv, this message translates to:
  /// **'Framme ca {clock} – före folk kommer ut'**
  String ferryEventReachBefore(String clock);

  /// No description provided for @ferryEventReachDuring.
  ///
  /// In sv, this message translates to:
  /// **'Framme ca {clock} – medan folk kommer ut'**
  String ferryEventReachDuring(String clock);

  /// No description provided for @ferryEventReachNoWindow.
  ///
  /// In sv, this message translates to:
  /// **'Framme ca {clock}'**
  String ferryEventReachNoWindow(String clock);

  /// No description provided for @ferryEventRowArrival.
  ///
  /// In sv, this message translates to:
  /// **'Ankomst'**
  String get ferryEventRowArrival;

  /// No description provided for @ferryEventRowAtQuay.
  ///
  /// In sv, this message translates to:
  /// **'Vid kajen'**
  String get ferryEventRowAtQuay;

  /// No description provided for @ferryEventRowCertainty.
  ///
  /// In sv, this message translates to:
  /// **'Hur säkert'**
  String get ferryEventRowCertainty;

  /// No description provided for @ferryEventRowComingFrom.
  ///
  /// In sv, this message translates to:
  /// **'Kommer från'**
  String get ferryEventRowComingFrom;

  /// No description provided for @ferryEventRowDelay.
  ///
  /// In sv, this message translates to:
  /// **'Försening'**
  String get ferryEventRowDelay;

  /// No description provided for @ferryEventRowDistance.
  ///
  /// In sv, this message translates to:
  /// **'Avstånd'**
  String get ferryEventRowDistance;

  /// No description provided for @ferryEventRowEndsAbout.
  ///
  /// In sv, this message translates to:
  /// **'Slutar ca'**
  String get ferryEventRowEndsAbout;

  /// No description provided for @ferryEventRowKind.
  ///
  /// In sv, this message translates to:
  /// **'Sort'**
  String get ferryEventRowKind;

  /// No description provided for @ferryEventRowOperator.
  ///
  /// In sv, this message translates to:
  /// **'Rederi'**
  String get ferryEventRowOperator;

  /// No description provided for @ferryEventRowPeopleCome.
  ///
  /// In sv, this message translates to:
  /// **'Folk kommer ut'**
  String get ferryEventRowPeopleCome;

  /// No description provided for @ferryEventRowPeopleLeaving.
  ///
  /// In sv, this message translates to:
  /// **'Folk på väg ut'**
  String get ferryEventRowPeopleLeaving;

  /// No description provided for @ferryEventRowQuay.
  ///
  /// In sv, this message translates to:
  /// **'Kaj'**
  String get ferryEventRowQuay;

  /// No description provided for @ferryEventRowReach.
  ///
  /// In sv, this message translates to:
  /// **'Hinner du'**
  String get ferryEventRowReach;

  /// No description provided for @ferryEventRowRoute.
  ///
  /// In sv, this message translates to:
  /// **'Linje'**
  String get ferryEventRowRoute;

  /// No description provided for @ferryEventRowSameQuay.
  ///
  /// In sv, this message translates to:
  /// **'Samma kaj ±30 min'**
  String get ferryEventRowSameQuay;

  /// No description provided for @ferryEventRowService.
  ///
  /// In sv, this message translates to:
  /// **'Trafik'**
  String get ferryEventRowService;

  /// No description provided for @ferryEventRowSize.
  ///
  /// In sv, this message translates to:
  /// **'Storlek'**
  String get ferryEventRowSize;

  /// No description provided for @ferryEventRowStatus.
  ///
  /// In sv, this message translates to:
  /// **'Status'**
  String get ferryEventRowStatus;

  /// No description provided for @ferryEventRowTimetable.
  ///
  /// In sv, this message translates to:
  /// **'Tidtabell'**
  String get ferryEventRowTimetable;

  /// No description provided for @ferryEventSameMany.
  ///
  /// In sv, this message translates to:
  /// **'{count, plural, other{{count} färjor till anländer}}'**
  String ferryEventSameMany(int count);

  /// No description provided for @ferryEventSameManyFirst.
  ///
  /// In sv, this message translates to:
  /// **'{count, plural, other{{count} färjor till anländer, första {at}}}'**
  String ferryEventSameManyFirst(int count, String at);

  /// No description provided for @ferryEventSameOne.
  ///
  /// In sv, this message translates to:
  /// **'1 färja till anländer'**
  String get ferryEventSameOne;

  /// No description provided for @ferryEventSameOneAt.
  ///
  /// In sv, this message translates to:
  /// **'1 färja till anländer {at}'**
  String ferryEventSameOneAt(String at);

  /// No description provided for @ferryEventSectionContext.
  ///
  /// In sv, this message translates to:
  /// **'Sammanhang'**
  String get ferryEventSectionContext;

  /// No description provided for @ferryEventSectionWhen.
  ///
  /// In sv, this message translates to:
  /// **'När'**
  String get ferryEventSectionWhen;

  /// No description provided for @ferryEventSectionWhere.
  ///
  /// In sv, this message translates to:
  /// **'Var'**
  String get ferryEventSectionWhere;

  /// No description provided for @ferryEventSectionWho.
  ///
  /// In sv, this message translates to:
  /// **'Vilka kliver av'**
  String get ferryEventSectionWho;

  /// No description provided for @ferryEventShouldHaveDocked.
  ///
  /// In sv, this message translates to:
  /// **'Skulle lägga till {clock} enligt tidtabell'**
  String ferryEventShouldHaveDocked(String clock);

  /// No description provided for @ferryEventSizeLarge.
  ///
  /// In sv, this message translates to:
  /// **'Stor färja'**
  String get ferryEventSizeLarge;

  /// No description provided for @ferryEventSizeMedium.
  ///
  /// In sv, this message translates to:
  /// **'Medelstor färja'**
  String get ferryEventSizeMedium;

  /// No description provided for @ferryEventSizeSmall.
  ///
  /// In sv, this message translates to:
  /// **'Mindre färja'**
  String get ferryEventSizeSmall;

  /// No description provided for @ferryEventTimeNotSet.
  ///
  /// In sv, this message translates to:
  /// **'Tid ej satt'**
  String get ferryEventTimeNotSet;

  /// No description provided for @ferryEventToday.
  ///
  /// In sv, this message translates to:
  /// **'i dag'**
  String get ferryEventToday;

  /// No description provided for @ferryEventTomorrow.
  ///
  /// In sv, this message translates to:
  /// **'i morgon'**
  String get ferryEventTomorrow;

  /// No description provided for @ferryEventUnknown.
  ///
  /// In sv, this message translates to:
  /// **'okänt'**
  String get ferryEventUnknown;

  /// No description provided for @ferryEventVenueCapacity.
  ///
  /// In sv, this message translates to:
  /// **'Arena för {capacity}'**
  String ferryEventVenueCapacity(String capacity);

  /// No description provided for @ferryEventVenueCapacityNote.
  ///
  /// In sv, this message translates to:
  /// **'arena för {capacity} (kapacitet, inte publik)'**
  String ferryEventVenueCapacityNote(String capacity);

  /// No description provided for @followUpCardClose.
  ///
  /// In sv, this message translates to:
  /// **'Stäng'**
  String get followUpCardClose;

  /// No description provided for @followUpCardDrove.
  ///
  /// In sv, this message translates to:
  /// **'Du körde mot {place} {time}'**
  String followUpCardDrove(String place, String time);

  /// No description provided for @forceUpgradeBody.
  ///
  /// In sv, this message translates to:
  /// **'Den här versionen fungerar inte längre. Uppdatera för att fortsätta.'**
  String get forceUpgradeBody;

  /// No description provided for @forceUpgradeClose.
  ///
  /// In sv, this message translates to:
  /// **'Stäng'**
  String get forceUpgradeClose;

  /// No description provided for @forceUpgradeNudge.
  ///
  /// In sv, this message translates to:
  /// **'Ny version finns. Uppdatera när du kan.'**
  String get forceUpgradeNudge;

  /// No description provided for @forceUpgradeTitle.
  ///
  /// In sv, this message translates to:
  /// **'Uppdatera appen'**
  String get forceUpgradeTitle;

  /// No description provided for @forceUpgradeUpdate.
  ///
  /// In sv, this message translates to:
  /// **'Uppdatera'**
  String get forceUpgradeUpdate;

  /// No description provided for @forceUpgradeVersions.
  ///
  /// In sv, this message translates to:
  /// **'Din version: {installed}  ·  Krävs: {required}'**
  String forceUpgradeVersions(String installed, String required);

  /// No description provided for @guidedTourDone.
  ///
  /// In sv, this message translates to:
  /// **'Klar'**
  String get guidedTourDone;

  /// No description provided for @guidedTourNext.
  ///
  /// In sv, this message translates to:
  /// **'Nästa'**
  String get guidedTourNext;

  /// No description provided for @guidedTourSkip.
  ///
  /// In sv, this message translates to:
  /// **'Hoppa över'**
  String get guidedTourSkip;

  /// No description provided for @guidedTourStep.
  ///
  /// In sv, this message translates to:
  /// **'Steg {position} av {total}'**
  String guidedTourStep(int position, int total);

  /// No description provided for @historyScreenAnd.
  ///
  /// In sv, this message translates to:
  /// **' och '**
  String get historyScreenAnd;

  /// No description provided for @historyScreenEarlier.
  ///
  /// In sv, this message translates to:
  /// **'Började tidigare'**
  String get historyScreenEarlier;

  /// No description provided for @historyScreenEnded.
  ///
  /// In sv, this message translates to:
  /// **'Slut'**
  String get historyScreenEnded;

  /// No description provided for @historyScreenHidden.
  ///
  /// In sv, this message translates to:
  /// **'{count} tips visas inte.'**
  String historyScreenHidden(int count);

  /// No description provided for @historyScreenHiddenIn.
  ///
  /// In sv, this message translates to:
  /// **'{count} tips i {categories} visas inte.'**
  String historyScreenHiddenIn(int count, String categories);

  /// No description provided for @historyScreenHours.
  ///
  /// In sv, this message translates to:
  /// **'{hours} tim'**
  String historyScreenHours(int hours);

  /// No description provided for @historyScreenLoadError.
  ///
  /// In sv, this message translates to:
  /// **'Kunde inte hämta historiken. Försök igen.'**
  String get historyScreenLoadError;

  /// No description provided for @historyScreenNeedsArea.
  ///
  /// In sv, this message translates to:
  /// **'Välj ditt körområde för att se historiken.'**
  String get historyScreenNeedsArea;

  /// No description provided for @historyScreenNoAccess.
  ///
  /// In sv, this message translates to:
  /// **'Historiken visas när telefonen har åtkomst till tips.'**
  String get historyScreenNoAccess;

  /// No description provided for @historyScreenNone.
  ///
  /// In sv, this message translates to:
  /// **'Inga tips de senaste {hours} timmarna.'**
  String historyScreenNone(int hours);

  /// No description provided for @historyScreenOngoing.
  ///
  /// In sv, this message translates to:
  /// **'Pågår'**
  String get historyScreenOngoing;

  /// No description provided for @historyScreenRetry.
  ///
  /// In sv, this message translates to:
  /// **'Försök igen'**
  String get historyScreenRetry;

  /// No description provided for @historyScreenShowingLatest.
  ///
  /// In sv, this message translates to:
  /// **'Visar de {count} senaste.'**
  String historyScreenShowingLatest(int count);

  /// No description provided for @historyScreenSummary.
  ///
  /// In sv, this message translates to:
  /// **'{count} tips de senaste {hours} timmarna · {active} pågår'**
  String historyScreenSummary(int count, int hours, int active);

  /// No description provided for @historyScreenTitle.
  ///
  /// In sv, this message translates to:
  /// **'Historik'**
  String get historyScreenTitle;

  /// No description provided for @historyScreenUnavailable.
  ///
  /// In sv, this message translates to:
  /// **'Historiken finns inte i den här versionen.'**
  String get historyScreenUnavailable;

  /// Tillgänglighetsetikett för språkknappen på välkomstskärmen
  ///
  /// In sv, this message translates to:
  /// **'Byt språk'**
  String get languageButtonLabel;

  /// No description provided for @languageCurrentAuto.
  ///
  /// In sv, this message translates to:
  /// **'{language} (telefonens språk)'**
  String languageCurrentAuto(String language);

  /// No description provided for @languageFollowPhone.
  ///
  /// In sv, this message translates to:
  /// **'Telefonens språk'**
  String get languageFollowPhone;

  /// No description provided for @languageFollowPhoneDetail.
  ///
  /// In sv, this message translates to:
  /// **'Nu: {language}'**
  String languageFollowPhoneDetail(String language);

  /// No description provided for @languageSectionDescription.
  ///
  /// In sv, this message translates to:
  /// **'Appen följer telefonens språk om den finns på det.'**
  String get languageSectionDescription;

  /// Rubrik för språkvalet i inställningarna och i väljaren
  ///
  /// In sv, this message translates to:
  /// **'Språk'**
  String get languageTitle;

  /// No description provided for @loginScreenBack.
  ///
  /// In sv, this message translates to:
  /// **'Tillbaka'**
  String get loginScreenBack;

  /// No description provided for @loginScreenCreateAccount.
  ///
  /// In sv, this message translates to:
  /// **'Skapa konto gratis'**
  String get loginScreenCreateAccount;

  /// No description provided for @loginScreenDeviceSwapLimit.
  ///
  /// In sv, this message translates to:
  /// **'Du har bytt telefon en gång den här månaden. Kontakta support så hjälper vi dig byta igen.'**
  String get loginScreenDeviceSwapLimit;

  /// No description provided for @loginScreenEmail.
  ///
  /// In sv, this message translates to:
  /// **'E-post'**
  String get loginScreenEmail;

  /// No description provided for @loginScreenEmailNotConfirmed.
  ///
  /// In sv, this message translates to:
  /// **'Bekräfta din e-post först. Tryck på länken i mejlet.'**
  String get loginScreenEmailNotConfirmed;

  /// No description provided for @loginScreenEnterCredentials.
  ///
  /// In sv, this message translates to:
  /// **'Skriv din e-post och ditt lösenord.'**
  String get loginScreenEnterCredentials;

  /// No description provided for @loginScreenFailed.
  ///
  /// In sv, this message translates to:
  /// **'Det gick inte att logga in. Försök igen.'**
  String get loginScreenFailed;

  /// No description provided for @loginScreenForgotPassword.
  ///
  /// In sv, this message translates to:
  /// **'Glömt lösenord?'**
  String get loginScreenForgotPassword;

  /// No description provided for @loginScreenHidePassword.
  ///
  /// In sv, this message translates to:
  /// **'Dölj lösenord'**
  String get loginScreenHidePassword;

  /// No description provided for @loginScreenIntro.
  ///
  /// In sv, this message translates to:
  /// **'För förare, ägare och kontor. Ny förare? Välj först ett lösenord med länken i inbjudan.'**
  String get loginScreenIntro;

  /// No description provided for @loginScreenNoAccount.
  ///
  /// In sv, this message translates to:
  /// **'Inget konto?'**
  String get loginScreenNoAccount;

  /// No description provided for @loginScreenNoInvite.
  ///
  /// In sv, this message translates to:
  /// **'Kontot är inte kopplat till något taxibolag. Be din chef bjuda in dig, eller tryck på Skapa konto gratis nedan.'**
  String get loginScreenNoInvite;

  /// No description provided for @loginScreenPassword.
  ///
  /// In sv, this message translates to:
  /// **'Lösenord'**
  String get loginScreenPassword;

  /// No description provided for @loginScreenRateLimit.
  ///
  /// In sv, this message translates to:
  /// **'Vänta en minut och försök igen.'**
  String get loginScreenRateLimit;

  /// No description provided for @loginScreenRecovered.
  ///
  /// In sv, this message translates to:
  /// **'Klart! Logga in med {email}.'**
  String loginScreenRecovered(String email);

  /// No description provided for @loginScreenShowPassword.
  ///
  /// In sv, this message translates to:
  /// **'Visa lösenord'**
  String get loginScreenShowPassword;

  /// Rubrik under loggan överst på inloggningen
  ///
  /// In sv, this message translates to:
  /// **'Se var folk behöver taxi,\ninnan kön växer.'**
  String get loginScreenTagline;

  /// Rubrik och knapptext på inloggningen
  ///
  /// In sv, this message translates to:
  /// **'Logga in'**
  String get loginScreenTitle;

  /// No description provided for @loginScreenWithBankId.
  ///
  /// In sv, this message translates to:
  /// **'Logga in med BankID'**
  String get loginScreenWithBankId;

  /// No description provided for @loginScreenWrongCredentials.
  ///
  /// In sv, this message translates to:
  /// **'Fel e-post eller lösenord.'**
  String get loginScreenWrongCredentials;

  /// No description provided for @membershipCopyAccessNotActive.
  ///
  /// In sv, this message translates to:
  /// **'Åtkomsten är inte aktiv.'**
  String get membershipCopyAccessNotActive;

  /// No description provided for @membershipCopyInvoicesOnWeb.
  ///
  /// In sv, this message translates to:
  /// **'Fakturor och medlemskap hanteras av företagets administratör på webben.'**
  String get membershipCopyInvoicesOnWeb;

  /// No description provided for @membershipCopyNotActive.
  ///
  /// In sv, this message translates to:
  /// **'Medlemskapet är inte aktivt just nu.'**
  String get membershipCopyNotActive;

  /// No description provided for @membershipCopyNotInMembership.
  ///
  /// In sv, this message translates to:
  /// **'Ingår inte i ditt medlemskap.'**
  String get membershipCopyNotInMembership;

  /// No description provided for @membershipCopyNotInTrial.
  ///
  /// In sv, this message translates to:
  /// **'Ingår inte i provet.'**
  String get membershipCopyNotInTrial;

  /// No description provided for @membershipCopyOnWeb.
  ///
  /// In sv, this message translates to:
  /// **'Ditt företags administratör hanterar medlemskapet på webben.'**
  String get membershipCopyOnWeb;

  /// No description provided for @membershipCopyPaused.
  ///
  /// In sv, this message translates to:
  /// **'Medlemskapet är pausat.'**
  String get membershipCopyPaused;

  /// No description provided for @membershipCopyPortalSubtitle.
  ///
  /// In sv, this message translates to:
  /// **'Öppnar kundportalen på webben: bilar, fakturor och medlemmar.'**
  String get membershipCopyPortalSubtitle;

  /// No description provided for @membershipCopyPortalTitle.
  ///
  /// In sv, this message translates to:
  /// **'Hantera företagskonto'**
  String get membershipCopyPortalTitle;

  /// No description provided for @membershipCopyPromiseNoBinding.
  ///
  /// In sv, this message translates to:
  /// **'Ingen bindning'**
  String get membershipCopyPromiseNoBinding;

  /// No description provided for @membershipCopyPromiseNoCard.
  ///
  /// In sv, this message translates to:
  /// **'Inget kort'**
  String get membershipCopyPromiseNoCard;

  /// No description provided for @membershipCopyPromiseNoCompany.
  ///
  /// In sv, this message translates to:
  /// **'Inget företag behövs'**
  String get membershipCopyPromiseNoCompany;

  /// No description provided for @membershipCopyTrialEnded.
  ///
  /// In sv, this message translates to:
  /// **'Provperioden är slut.'**
  String get membershipCopyTrialEnded;

  /// No description provided for @membershipCountyContinue.
  ///
  /// In sv, this message translates to:
  /// **'Fortsätt'**
  String get membershipCountyContinue;

  /// No description provided for @membershipCountyLoadFailed.
  ///
  /// In sv, this message translates to:
  /// **'Kunde inte hämta länen. Dra ner för att försöka igen.'**
  String get membershipCountyLoadFailed;

  /// No description provided for @membershipCountyRetry.
  ///
  /// In sv, this message translates to:
  /// **'Försök igen'**
  String get membershipCountyRetry;

  /// No description provided for @membershipCountySubtitle.
  ///
  /// In sv, this message translates to:
  /// **'Välj länet där du kör mest. Du kan byta senare.'**
  String get membershipCountySubtitle;

  /// No description provided for @membershipCountyTitle.
  ///
  /// In sv, this message translates to:
  /// **'Var vill du köra?'**
  String get membershipCountyTitle;

  /// No description provided for @netStatusGenericError.
  ///
  /// In sv, this message translates to:
  /// **'Något gick fel. Försök igen.'**
  String get netStatusGenericError;

  /// No description provided for @netStatusOffline.
  ///
  /// In sv, this message translates to:
  /// **'Ingen internetanslutning'**
  String get netStatusOffline;

  /// No description provided for @netStatusTimeout.
  ///
  /// In sv, this message translates to:
  /// **'Dålig uppkoppling. Försök igen.'**
  String get netStatusTimeout;

  /// No description provided for @netStatusUnreachable.
  ///
  /// In sv, this message translates to:
  /// **'Servern svarar inte just nu'**
  String get netStatusUnreachable;

  /// No description provided for @notificationLogSheetArchived.
  ///
  /// In sv, this message translates to:
  /// **'· arkiverad'**
  String get notificationLogSheetArchived;

  /// No description provided for @notificationLogSheetEmptyBody.
  ///
  /// In sv, this message translates to:
  /// **'Notiser skickas bara för störningar som är värda att avbryta för. Är det lugnt i dina län hör du inget — och det är meningen.'**
  String get notificationLogSheetEmptyBody;

  /// No description provided for @notificationLogSheetEmptyTitle.
  ///
  /// In sv, this message translates to:
  /// **'Inga notiser än'**
  String get notificationLogSheetEmptyTitle;

  /// No description provided for @notificationLogSheetHoursAgo.
  ///
  /// In sv, this message translates to:
  /// **'För {hours} tim sedan'**
  String notificationLogSheetHoursAgo(int hours);

  /// No description provided for @notificationLogSheetIntro.
  ///
  /// In sv, this message translates to:
  /// **'Notiser som skickats till den här telefonen. Vill du spara ett tips? Gör det med stjärnan i tipslistan — då ligger det under Sparat i sju dagar.'**
  String get notificationLogSheetIntro;

  /// No description provided for @notificationLogSheetMinAgo.
  ///
  /// In sv, this message translates to:
  /// **'För {minutes} min sedan'**
  String notificationLogSheetMinAgo(int minutes);

  /// No description provided for @notificationLogSheetNeedsBackend.
  ///
  /// In sv, this message translates to:
  /// **'Notishistorik kräver backend'**
  String get notificationLogSheetNeedsBackend;

  /// No description provided for @notificationLogSheetNoPhone.
  ///
  /// In sv, this message translates to:
  /// **'Ingen parad telefon'**
  String get notificationLogSheetNoPhone;

  /// No description provided for @notificationLogSheetNoPhoneBody.
  ///
  /// In sv, this message translates to:
  /// **'Notiser skickas till en parad enhet. Den här inloggningen har ingen.'**
  String get notificationLogSheetNoPhoneBody;

  /// No description provided for @notificationLogSheetNow.
  ///
  /// In sv, this message translates to:
  /// **'Just nu'**
  String get notificationLogSheetNow;

  /// No description provided for @notificationLogSheetTitle.
  ///
  /// In sv, this message translates to:
  /// **'Mina notiser'**
  String get notificationLogSheetTitle;

  /// No description provided for @notifyPrefsAreaLine.
  ///
  /// In sv, this message translates to:
  /// **'Körområde: {counties}'**
  String notifyPrefsAreaLine(String counties);

  /// No description provided for @notifyPrefsByArea.
  ///
  /// In sv, this message translates to:
  /// **'Enligt körområdet'**
  String get notifyPrefsByArea;

  /// No description provided for @notifyPrefsHowImportant.
  ///
  /// In sv, this message translates to:
  /// **'Hur viktiga?'**
  String get notifyPrefsHowImportant;

  /// No description provided for @notifyPrefsLevelAll.
  ///
  /// In sv, this message translates to:
  /// **'Alla'**
  String get notifyPrefsLevelAll;

  /// No description provided for @notifyPrefsLevelMedium.
  ///
  /// In sv, this message translates to:
  /// **'Medel +'**
  String get notifyPrefsLevelMedium;

  /// No description provided for @notifyPrefsLevelStrong.
  ///
  /// In sv, this message translates to:
  /// **'Starka'**
  String get notifyPrefsLevelStrong;

  /// No description provided for @notifyPrefsMoreOptions.
  ///
  /// In sv, this message translates to:
  /// **'Fler val'**
  String get notifyPrefsMoreOptions;

  /// No description provided for @notifyPrefsNeedsLocation.
  ///
  /// In sv, this message translates to:
  /// **'I tjänst behöver plats när appen används'**
  String get notifyPrefsNeedsLocation;

  /// No description provided for @notifyPrefsNoActiveSeat.
  ///
  /// In sv, this message translates to:
  /// **'Ingen aktiv plats på den här enheten — inställningarna kan inte sparas.'**
  String get notifyPrefsNoActiveSeat;

  /// No description provided for @notifyPrefsOnAgain.
  ///
  /// In sv, this message translates to:
  /// **'Notiserna är på igen.'**
  String get notifyPrefsOnAgain;

  /// No description provided for @notifyPrefsOnDuty.
  ///
  /// In sv, this message translates to:
  /// **'I tjänst'**
  String get notifyPrefsOnDuty;

  /// No description provided for @notifyPrefsPause.
  ///
  /// In sv, this message translates to:
  /// **'Paus'**
  String get notifyPrefsPause;

  /// No description provided for @notifyPrefsPause1h.
  ///
  /// In sv, this message translates to:
  /// **'1 tim'**
  String get notifyPrefsPause1h;

  /// No description provided for @notifyPrefsPause4h.
  ///
  /// In sv, this message translates to:
  /// **'4 tim'**
  String get notifyPrefsPause4h;

  /// No description provided for @notifyPrefsPauseTonight.
  ///
  /// In sv, this message translates to:
  /// **'I natt'**
  String get notifyPrefsPauseTonight;

  /// No description provided for @notifyPrefsPausedUntilSnack.
  ///
  /// In sv, this message translates to:
  /// **'Pausat till {time}.'**
  String notifyPrefsPausedUntilSnack(String time);

  /// No description provided for @notifyPrefsPausedUntilTitle.
  ///
  /// In sv, this message translates to:
  /// **'Pausat till {time}'**
  String notifyPrefsPausedUntilTitle(String time);

  /// No description provided for @notifyPrefsResume.
  ///
  /// In sv, this message translates to:
  /// **'Starta igen'**
  String get notifyPrefsResume;

  /// No description provided for @notifyPrefsSaved.
  ///
  /// In sv, this message translates to:
  /// **'Sparat'**
  String get notifyPrefsSaved;

  /// No description provided for @notifyPrefsSendNotifications.
  ///
  /// In sv, this message translates to:
  /// **'Skicka notiser'**
  String get notifyPrefsSendNotifications;

  /// No description provided for @notifyPrefsTitle.
  ///
  /// In sv, this message translates to:
  /// **'Notiser'**
  String get notifyPrefsTitle;

  /// No description provided for @notifyPrefsTomorrowAt.
  ///
  /// In sv, this message translates to:
  /// **'i morgon {time}'**
  String notifyPrefsTomorrowAt(String time);

  /// No description provided for @notifyPrefsWhichNotifications.
  ///
  /// In sv, this message translates to:
  /// **'Vilka notiser?'**
  String get notifyPrefsWhichNotifications;

  /// No description provided for @notifyPrefsWithinKm.
  ///
  /// In sv, this message translates to:
  /// **'Inom 30 km av dig'**
  String get notifyPrefsWithinKm;

  /// No description provided for @notifyRulesApiInvalidResponse.
  ///
  /// In sv, this message translates to:
  /// **'Ogiltigt svar från servern'**
  String get notifyRulesApiInvalidResponse;

  /// No description provided for @notifyRulesApiServerResponded.
  ///
  /// In sv, this message translates to:
  /// **'Servern svarade {status}'**
  String notifyRulesApiServerResponded(int status);

  /// No description provided for @offlineBannerOffline.
  ///
  /// In sv, this message translates to:
  /// **'Offline – visar senaste tips från {at}'**
  String offlineBannerOffline(String at);

  /// No description provided for @offlineBannerRetry.
  ///
  /// In sv, this message translates to:
  /// **'Försök igen'**
  String get offlineBannerRetry;

  /// No description provided for @offlineBannerTimeout.
  ///
  /// In sv, this message translates to:
  /// **'Dålig uppkoppling – visar tips från {at}'**
  String offlineBannerTimeout(String at);

  /// No description provided for @offlineBannerUnreachable.
  ///
  /// In sv, this message translates to:
  /// **'Servern svarar inte – visar tips från {at}'**
  String offlineBannerUnreachable(String at);

  /// No description provided for @onboardingScreenClose.
  ///
  /// In sv, this message translates to:
  /// **'Stäng'**
  String get onboardingScreenClose;

  /// No description provided for @onboardingScreenColorsBody.
  ///
  /// In sv, this message translates to:
  /// **'Det är tips, inte beställningar. Du avgör själv om det är värt att åka.'**
  String get onboardingScreenColorsBody;

  /// No description provided for @onboardingScreenColorsTitle.
  ///
  /// In sv, this message translates to:
  /// **'Färgen visar hur starkt tipset är'**
  String get onboardingScreenColorsTitle;

  /// No description provided for @onboardingScreenDone.
  ///
  /// In sv, this message translates to:
  /// **'Klar'**
  String get onboardingScreenDone;

  /// No description provided for @onboardingScreenFeedbackBody.
  ///
  /// In sv, this message translates to:
  /// **'Tryck på ett tips och välj Fick körning eller Ingen kund. Då blir tipsen bättre för alla.'**
  String get onboardingScreenFeedbackBody;

  /// No description provided for @onboardingScreenFeedbackTitle.
  ///
  /// In sv, this message translates to:
  /// **'Säg hur det gick'**
  String get onboardingScreenFeedbackTitle;

  /// No description provided for @onboardingScreenLevelMedium.
  ///
  /// In sv, this message translates to:
  /// **'Medel'**
  String get onboardingScreenLevelMedium;

  /// No description provided for @onboardingScreenLevelMediumText.
  ///
  /// In sv, this message translates to:
  /// **'Kan bli körningar. Håll koll.'**
  String get onboardingScreenLevelMediumText;

  /// No description provided for @onboardingScreenLevelStrong.
  ///
  /// In sv, this message translates to:
  /// **'Stark'**
  String get onboardingScreenLevelStrong;

  /// No description provided for @onboardingScreenLevelStrongText.
  ///
  /// In sv, this message translates to:
  /// **'Många kan behöva taxi.'**
  String get onboardingScreenLevelStrongText;

  /// No description provided for @onboardingScreenLevelWeak.
  ///
  /// In sv, this message translates to:
  /// **'Svag'**
  String get onboardingScreenLevelWeak;

  /// No description provided for @onboardingScreenLevelWeakText.
  ///
  /// In sv, this message translates to:
  /// **'Bra att veta, sällan värt att åka.'**
  String get onboardingScreenLevelWeakText;

  /// No description provided for @onboardingScreenNext.
  ///
  /// In sv, this message translates to:
  /// **'Nästa'**
  String get onboardingScreenNext;

  /// No description provided for @onboardingScreenNotifBody.
  ///
  /// In sv, this message translates to:
  /// **'Slå på notiser under Inställningar. Då säger vi till när ett starkt tips dyker upp nära dig.'**
  String get onboardingScreenNotifBody;

  /// No description provided for @onboardingScreenNotifTitle.
  ///
  /// In sv, this message translates to:
  /// **'Notiser'**
  String get onboardingScreenNotifTitle;

  /// No description provided for @onboardingScreenPageOf.
  ///
  /// In sv, this message translates to:
  /// **'Sida {page} av {total}'**
  String onboardingScreenPageOf(int page, int total);

  /// No description provided for @onboardingScreenSkip.
  ///
  /// In sv, this message translates to:
  /// **'Hoppa över'**
  String get onboardingScreenSkip;

  /// No description provided for @onboardingScreenStartBody.
  ///
  /// In sv, this message translates to:
  /// **'Skapa ett konto gratis, eller logga in om du redan har ett. Sedan visar vi dig runt i appen.'**
  String get onboardingScreenStartBody;

  /// Rubrik på sista sidan och knapptext
  ///
  /// In sv, this message translates to:
  /// **'Kom igång'**
  String get onboardingScreenStartTitle;

  /// No description provided for @onboardingScreenTrafficBody.
  ///
  /// In sv, this message translates to:
  /// **'Inställda tåg, sena flyg, färjor och event som slutar. Vi visar var folk kan behöva taxi. Det är tips, inte beställningar.'**
  String get onboardingScreenTrafficBody;

  /// No description provided for @onboardingScreenTrafficTitle.
  ///
  /// In sv, this message translates to:
  /// **'Tips från trafiken'**
  String get onboardingScreenTrafficTitle;

  /// No description provided for @settingsScreenAboutTips.
  ///
  /// In sv, this message translates to:
  /// **'Om tipsen'**
  String get settingsScreenAboutTips;

  /// No description provided for @settingsScreenAccountClosed.
  ///
  /// In sv, this message translates to:
  /// **'Kontot är avslutat.'**
  String get settingsScreenAccountClosed;

  /// No description provided for @settingsScreenAccountDescription.
  ///
  /// In sv, this message translates to:
  /// **'Logga ut om du slutar köra eller byter telefon.'**
  String get settingsScreenAccountDescription;

  /// No description provided for @settingsScreenAccountTitle.
  ///
  /// In sv, this message translates to:
  /// **'Konto'**
  String get settingsScreenAccountTitle;

  /// No description provided for @settingsScreenCancel.
  ///
  /// In sv, this message translates to:
  /// **'Avbryt'**
  String get settingsScreenCancel;

  /// No description provided for @settingsScreenCloseAccountBody.
  ///
  /// In sv, this message translates to:
  /// **'Medlemskapet förnyas inte. Pågår ett prov avslutas det. Ni kan använda appen perioden ut.'**
  String get settingsScreenCloseAccountBody;

  /// No description provided for @settingsScreenCloseAccountConfirm.
  ///
  /// In sv, this message translates to:
  /// **'Avsluta'**
  String get settingsScreenCloseAccountConfirm;

  /// No description provided for @settingsScreenCloseAccountTitle.
  ///
  /// In sv, this message translates to:
  /// **'Avsluta företagskontot?'**
  String get settingsScreenCloseAccountTitle;

  /// No description provided for @settingsScreenCloseCompanyAccount.
  ///
  /// In sv, this message translates to:
  /// **'Avsluta företagskontot'**
  String get settingsScreenCloseCompanyAccount;

  /// No description provided for @settingsScreenCompanyDescription.
  ///
  /// In sv, this message translates to:
  /// **'Hantera företagskontot i kundportalen på webben.'**
  String get settingsScreenCompanyDescription;

  /// No description provided for @settingsScreenCompanyTitle.
  ///
  /// In sv, this message translates to:
  /// **'Företaget'**
  String get settingsScreenCompanyTitle;

  /// No description provided for @settingsScreenCountiesMany.
  ///
  /// In sv, this message translates to:
  /// **'Tips och notiser i dina län. Tryck för att välja vilka.'**
  String get settingsScreenCountiesMany;

  /// No description provided for @settingsScreenCountiesOne.
  ///
  /// In sv, this message translates to:
  /// **'Tips och notiser i det här länet.'**
  String get settingsScreenCountiesOne;

  /// No description provided for @settingsScreenDelete.
  ///
  /// In sv, this message translates to:
  /// **'Radera'**
  String get settingsScreenDelete;

  /// No description provided for @settingsScreenDeleteBodyDriver.
  ///
  /// In sv, this message translates to:
  /// **'Ditt förarkonto tas bort och enheten kopplas från din plats. Din chef kan bjuda in dig igen. Det går inte att ångra.'**
  String get settingsScreenDeleteBodyDriver;

  /// No description provided for @settingsScreenDeleteBodyOffice.
  ///
  /// In sv, this message translates to:
  /// **'Ditt konto och din inloggning tas bort för gott. Enheter du kört med kopplas från medlemskapet.\n\nÄr du ensam ägare avslutas företaget direkt: medlemskapet och ett pågående prov upphör, förarna slutar få tips och företaget arkiveras. Det går inte att ångra.'**
  String get settingsScreenDeleteBodyOffice;

  /// No description provided for @settingsScreenDeleteFailedTitle.
  ///
  /// In sv, this message translates to:
  /// **'Kontot raderades inte'**
  String get settingsScreenDeleteFailedTitle;

  /// No description provided for @settingsScreenDeleteMyAccount.
  ///
  /// In sv, this message translates to:
  /// **'Radera mitt konto'**
  String get settingsScreenDeleteMyAccount;

  /// No description provided for @settingsScreenDeleteTitle.
  ///
  /// In sv, this message translates to:
  /// **'Radera ditt konto?'**
  String get settingsScreenDeleteTitle;

  /// No description provided for @settingsScreenDeleted.
  ///
  /// In sv, this message translates to:
  /// **'Ditt konto är raderat.'**
  String get settingsScreenDeleted;

  /// No description provided for @settingsScreenHelpChat.
  ///
  /// In sv, this message translates to:
  /// **'Chatta med oss'**
  String get settingsScreenHelpChat;

  /// No description provided for @settingsScreenHelpDescription.
  ///
  /// In sv, this message translates to:
  /// **'Se hur appen fungerar, eller skriv till oss.'**
  String get settingsScreenHelpDescription;

  /// No description provided for @settingsScreenHelpHowDriver.
  ///
  /// In sv, this message translates to:
  /// **'Fyra korta sidor'**
  String get settingsScreenHelpHowDriver;

  /// No description provided for @settingsScreenHelpHowItWorks.
  ///
  /// In sv, this message translates to:
  /// **'Så fungerar Taxi Tips'**
  String get settingsScreenHelpHowItWorks;

  /// No description provided for @settingsScreenHelpHowOffice.
  ///
  /// In sv, this message translates to:
  /// **'Provet, medlemskap och förare'**
  String get settingsScreenHelpHowOffice;

  /// No description provided for @settingsScreenHelpTitle.
  ///
  /// In sv, this message translates to:
  /// **'Hjälp'**
  String get settingsScreenHelpTitle;

  /// No description provided for @settingsScreenHelpTour.
  ///
  /// In sv, this message translates to:
  /// **'Visa genomgången igen'**
  String get settingsScreenHelpTour;

  /// No description provided for @settingsScreenHelpTourSub.
  ///
  /// In sv, this message translates to:
  /// **'Visar var du trycker på startsidan'**
  String get settingsScreenHelpTourSub;

  /// No description provided for @settingsScreenHelpUnread.
  ///
  /// In sv, this message translates to:
  /// **'{count, plural, =1{Ett nytt svar} other{{count} nya svar}}'**
  String settingsScreenHelpUnread(int count);

  /// No description provided for @settingsScreenLoginForSettings.
  ///
  /// In sv, this message translates to:
  /// **'Logga in för att se inställningarna.'**
  String get settingsScreenLoginForSettings;

  /// No description provided for @settingsScreenLogout.
  ///
  /// In sv, this message translates to:
  /// **'Logga ut'**
  String get settingsScreenLogout;

  /// No description provided for @settingsScreenMembershipDescription.
  ///
  /// In sv, this message translates to:
  /// **'Platsen du kör med och länen du får tips från.'**
  String get settingsScreenMembershipDescription;

  /// No description provided for @settingsScreenMembershipDescriptionCompany.
  ///
  /// In sv, this message translates to:
  /// **'Platsen du kör med och länen du får tips från. Företag: {company}.'**
  String settingsScreenMembershipDescriptionCompany(String company);

  /// No description provided for @settingsScreenMembershipTitle.
  ///
  /// In sv, this message translates to:
  /// **'Medlemskap'**
  String get settingsScreenMembershipTitle;

  /// No description provided for @settingsScreenNotifyAllCounties.
  ///
  /// In sv, this message translates to:
  /// **'Alla dina län'**
  String get settingsScreenNotifyAllCounties;

  /// No description provided for @settingsScreenNotifyDescription.
  ///
  /// In sv, this message translates to:
  /// **'Välj när telefonen ska säga till om ett starkt tips.'**
  String get settingsScreenNotifyDescription;

  /// No description provided for @settingsScreenNotifyFilter.
  ///
  /// In sv, this message translates to:
  /// **'Filter: {counties}'**
  String settingsScreenNotifyFilter(String counties);

  /// No description provided for @settingsScreenNotifyTitle.
  ///
  /// In sv, this message translates to:
  /// **'Notiser'**
  String get settingsScreenNotifyTitle;

  /// No description provided for @settingsScreenOk.
  ///
  /// In sv, this message translates to:
  /// **'OK'**
  String get settingsScreenOk;

  /// No description provided for @settingsScreenPrivacy.
  ///
  /// In sv, this message translates to:
  /// **'Datapolicy'**
  String get settingsScreenPrivacy;

  /// No description provided for @settingsScreenSignedInAs.
  ///
  /// In sv, this message translates to:
  /// **'Inloggad som'**
  String get settingsScreenSignedInAs;

  /// No description provided for @settingsScreenTerms.
  ///
  /// In sv, this message translates to:
  /// **'Villkor'**
  String get settingsScreenTerms;

  /// No description provided for @settingsScreenTitle.
  ///
  /// In sv, this message translates to:
  /// **'Inställningar'**
  String get settingsScreenTitle;

  /// No description provided for @settingsScreenYourCounties.
  ///
  /// In sv, this message translates to:
  /// **'Dina län'**
  String get settingsScreenYourCounties;

  /// No description provided for @severityLabelsCancelledAt.
  ///
  /// In sv, this message translates to:
  /// **'Inställd {clock}'**
  String severityLabelsCancelledAt(String clock);

  /// No description provided for @severityLabelsClockChange.
  ///
  /// In sv, this message translates to:
  /// **'{from} → {to}'**
  String severityLabelsClockChange(String from, String to);

  /// No description provided for @severityLabelsCompensationBase.
  ///
  /// In sv, this message translates to:
  /// **'Resenären kan få taxin betald'**
  String get severityLabelsCompensationBase;

  /// No description provided for @severityLabelsCompensationMaybe.
  ///
  /// In sv, this message translates to:
  /// **'Taxi kan ersättas'**
  String get severityLabelsCompensationMaybe;

  /// No description provided for @severityLabelsCompensationSentenceUpTo.
  ///
  /// In sv, this message translates to:
  /// **'Resenären kan få taxin betald upp till {amount} kr{per, select, person{ per resenär} trip{ per resa} other{}}'**
  String severityLabelsCompensationSentenceUpTo(String amount, String per);

  /// No description provided for @severityLabelsCompensationUpTo.
  ///
  /// In sv, this message translates to:
  /// **'Taxi ersätts · upp till {amount} kr{per, select, person{ per resenär} trip{ per resa} other{}}'**
  String severityLabelsCompensationUpTo(int amount, String per);

  /// No description provided for @severityLabelsConfidenceHigh.
  ///
  /// In sv, this message translates to:
  /// **'Hög — tydligt i källdatan'**
  String get severityLabelsConfidenceHigh;

  /// No description provided for @severityLabelsConfidenceLow.
  ///
  /// In sv, this message translates to:
  /// **'Låg — osäker tolkning av källdatan'**
  String get severityLabelsConfidenceLow;

  /// No description provided for @severityLabelsConfidenceMedium.
  ///
  /// In sv, this message translates to:
  /// **'Medel'**
  String get severityLabelsConfidenceMedium;

  /// No description provided for @severityLabelsDelayed.
  ///
  /// In sv, this message translates to:
  /// **'Försenad'**
  String get severityLabelsDelayed;

  /// No description provided for @severityLabelsDelayedBy.
  ///
  /// In sv, this message translates to:
  /// **'Försenad {delay}'**
  String severityLabelsDelayedBy(String delay);

  /// No description provided for @severityLabelsDeparted.
  ///
  /// In sv, this message translates to:
  /// **'har gått'**
  String get severityLabelsDeparted;

  /// No description provided for @severityLabelsDepartsNow.
  ///
  /// In sv, this message translates to:
  /// **'avgår nu'**
  String get severityLabelsDepartsNow;

  /// No description provided for @severityLabelsHours.
  ///
  /// In sv, this message translates to:
  /// **'{hours} tim'**
  String severityLabelsHours(int hours);

  /// No description provided for @severityLabelsHoursMinutes.
  ///
  /// In sv, this message translates to:
  /// **'{hours} tim {minutes} min'**
  String severityLabelsHoursMinutes(int hours, int minutes);

  /// No description provided for @severityLabelsIn.
  ///
  /// In sv, this message translates to:
  /// **'om {time}'**
  String severityLabelsIn(String time);

  /// No description provided for @severityLabelsMinutes.
  ///
  /// In sv, this message translates to:
  /// **'{minutes} min'**
  String severityLabelsMinutes(int minutes);

  /// No description provided for @severityLabelsModeBoat.
  ///
  /// In sv, this message translates to:
  /// **'Båt'**
  String get severityLabelsModeBoat;

  /// No description provided for @severityLabelsModeBus.
  ///
  /// In sv, this message translates to:
  /// **'Buss'**
  String get severityLabelsModeBus;

  /// No description provided for @severityLabelsModeEvents.
  ///
  /// In sv, this message translates to:
  /// **'Evenemang'**
  String get severityLabelsModeEvents;

  /// No description provided for @severityLabelsModeFerries.
  ///
  /// In sv, this message translates to:
  /// **'Färjor'**
  String get severityLabelsModeFerries;

  /// No description provided for @severityLabelsModeFlight.
  ///
  /// In sv, this message translates to:
  /// **'Flyg'**
  String get severityLabelsModeFlight;

  /// No description provided for @severityLabelsModeMetro.
  ///
  /// In sv, this message translates to:
  /// **'Tunnelbana'**
  String get severityLabelsModeMetro;

  /// No description provided for @severityLabelsModeRoad.
  ///
  /// In sv, this message translates to:
  /// **'Väg'**
  String get severityLabelsModeRoad;

  /// No description provided for @severityLabelsModeTrain.
  ///
  /// In sv, this message translates to:
  /// **'Tåg'**
  String get severityLabelsModeTrain;

  /// No description provided for @severityLabelsModeTram.
  ///
  /// In sv, this message translates to:
  /// **'Spårvagn'**
  String get severityLabelsModeTram;

  /// No description provided for @severityLabelsMonthShort.
  ///
  /// In sv, this message translates to:
  /// **'{m, select, m1{jan} m2{feb} m3{mar} m4{apr} m5{maj} m6{jun} m7{jul} m8{aug} m9{sep} m10{okt} m11{nov} m12{dec} other{}}'**
  String severityLabelsMonthShort(String m);

  /// No description provided for @severityLabelsShortArrivalWave.
  ///
  /// In sv, this message translates to:
  /// **'Ankomstvåg'**
  String get severityLabelsShortArrivalWave;

  /// No description provided for @severityLabelsShortIgnore.
  ///
  /// In sv, this message translates to:
  /// **'Övrigt'**
  String get severityLabelsShortIgnore;

  /// No description provided for @severityLabelsShortLastArrival.
  ///
  /// In sv, this message translates to:
  /// **'Sista ankomsten'**
  String get severityLabelsShortLastArrival;

  /// No description provided for @severityLabelsShortLineDelayed.
  ///
  /// In sv, this message translates to:
  /// **'Försening, linjen kör'**
  String get severityLabelsShortLineDelayed;

  /// No description provided for @severityLabelsShortLinePaused.
  ///
  /// In sv, this message translates to:
  /// **'Hela linjen stoppad'**
  String get severityLabelsShortLinePaused;

  /// No description provided for @severityLabelsShortRoadAccident.
  ///
  /// In sv, this message translates to:
  /// **'Olycka/avstängning'**
  String get severityLabelsShortRoadAccident;

  /// No description provided for @severityLabelsShortRoadWork.
  ///
  /// In sv, this message translates to:
  /// **'Vägarbete'**
  String get severityLabelsShortRoadWork;

  /// No description provided for @severityLabelsShortRoadWorkQueue.
  ///
  /// In sv, this message translates to:
  /// **'Vägarbete/kö'**
  String get severityLabelsShortRoadWorkQueue;

  /// No description provided for @severityLabelsShortUnclassified.
  ///
  /// In sv, this message translates to:
  /// **'Osäker bedömning'**
  String get severityLabelsShortUnclassified;

  /// No description provided for @severityLabelsShortVehicleCancelled.
  ///
  /// In sv, this message translates to:
  /// **'Enstaka avgång inställd'**
  String get severityLabelsShortVehicleCancelled;

  /// No description provided for @severityLabelsShortVehicleDelayed.
  ///
  /// In sv, this message translates to:
  /// **'Enstaka avgång försenad'**
  String get severityLabelsShortVehicleDelayed;

  /// No description provided for @severityLabelsTierArrivalWave.
  ///
  /// In sv, this message translates to:
  /// **'Många flyg landar samtidigt'**
  String get severityLabelsTierArrivalWave;

  /// No description provided for @severityLabelsTierArrivalWaveFerry.
  ///
  /// In sv, this message translates to:
  /// **'Många färjor kommer in samtidigt'**
  String get severityLabelsTierArrivalWaveFerry;

  /// No description provided for @severityLabelsTierIgnore.
  ///
  /// In sv, this message translates to:
  /// **'Övrigt – trafikbolagets meddelande'**
  String get severityLabelsTierIgnore;

  /// No description provided for @severityLabelsTierLastArrival.
  ///
  /// In sv, this message translates to:
  /// **'Sista planet — inget mer landar på flera timmar'**
  String get severityLabelsTierLastArrival;

  /// No description provided for @severityLabelsTierLastArrivalFerry.
  ///
  /// In sv, this message translates to:
  /// **'Sista färjan — inget mer anländer på flera timmar'**
  String get severityLabelsTierLastArrivalFerry;

  /// No description provided for @severityLabelsTierLineDelayed.
  ///
  /// In sv, this message translates to:
  /// **'Försening på linjen'**
  String get severityLabelsTierLineDelayed;

  /// No description provided for @severityLabelsTierLinePaused.
  ///
  /// In sv, this message translates to:
  /// **'Hela linjen är stoppad'**
  String get severityLabelsTierLinePaused;

  /// No description provided for @severityLabelsTierRoadAccident.
  ///
  /// In sv, this message translates to:
  /// **'Olycka eller avstängd väg'**
  String get severityLabelsTierRoadAccident;

  /// No description provided for @severityLabelsTierRoadWork.
  ///
  /// In sv, this message translates to:
  /// **'Mindre vägarbete'**
  String get severityLabelsTierRoadWork;

  /// No description provided for @severityLabelsTierRoadWorkQueue.
  ///
  /// In sv, this message translates to:
  /// **'Vägarbete eller köbildning'**
  String get severityLabelsTierRoadWorkQueue;

  /// No description provided for @severityLabelsTierUnclassified.
  ///
  /// In sv, this message translates to:
  /// **'Störning (osäker klassificering)'**
  String get severityLabelsTierUnclassified;

  /// No description provided for @severityLabelsTierVehicleCancelled.
  ///
  /// In sv, this message translates to:
  /// **'En avgång inställd'**
  String get severityLabelsTierVehicleCancelled;

  /// No description provided for @severityLabelsTierVehicleDelayed.
  ///
  /// In sv, this message translates to:
  /// **'En avgång försenad'**
  String get severityLabelsTierVehicleDelayed;

  /// No description provided for @severityLabelsTipFallback.
  ///
  /// In sv, this message translates to:
  /// **'Tips'**
  String get severityLabelsTipFallback;

  /// No description provided for @severityLabelsTitleWithMode.
  ///
  /// In sv, this message translates to:
  /// **'{mode}: {title}'**
  String severityLabelsTitleWithMode(String mode, String title);

  /// No description provided for @severityLabelsTowards.
  ///
  /// In sv, this message translates to:
  /// **'mot {destination}'**
  String severityLabelsTowards(String destination);

  /// No description provided for @severityLabelsWaitLast.
  ///
  /// In sv, this message translates to:
  /// **'Sista avgången härifrån'**
  String get severityLabelsWaitLast;

  /// No description provided for @severityLabelsWaitThere.
  ///
  /// In sv, this message translates to:
  /// **'Nästa dit{at}, {gap} senare'**
  String severityLabelsWaitThere(String at, String gap);

  /// No description provided for @severityLabelsWaitThereFirst.
  ///
  /// In sv, this message translates to:
  /// **'Nästa dit först{at}, {gap} senare'**
  String severityLabelsWaitThereFirst(String at, String gap);

  /// No description provided for @severityLabelsWaitTrip.
  ///
  /// In sv, this message translates to:
  /// **'Nästa resa{at}, {gap} senare'**
  String severityLabelsWaitTrip(String at, String gap);

  /// No description provided for @severityLabelsWaitTripFirst.
  ///
  /// In sv, this message translates to:
  /// **'Nästa resa först{at}, {gap} senare'**
  String severityLabelsWaitTripFirst(String at, String gap);

  /// No description provided for @signalCardDrive.
  ///
  /// In sv, this message translates to:
  /// **'Kör dit'**
  String get signalCardDrive;

  /// No description provided for @signalCardNoteBody.
  ///
  /// In sv, this message translates to:
  /// **'Vi läser av trafiken och visar var folk kan behöva taxi. Du avgör själv om det är värt att åka.'**
  String get signalCardNoteBody;

  /// No description provided for @signalCardNoteLine.
  ///
  /// In sv, this message translates to:
  /// **'Tips från trafikläget, ingen garanti för körning'**
  String get signalCardNoteLine;

  /// No description provided for @signalCardNoteMore.
  ///
  /// In sv, this message translates to:
  /// **'{title}. Visa mer'**
  String signalCardNoteMore(String title);

  /// No description provided for @signalCardNoteOk.
  ///
  /// In sv, this message translates to:
  /// **'Uppfattat'**
  String get signalCardNoteOk;

  /// No description provided for @signalCardNoteTitle.
  ///
  /// In sv, this message translates to:
  /// **'Tips, inte beställningar'**
  String get signalCardNoteTitle;

  /// No description provided for @signalCardOver.
  ///
  /// In sv, this message translates to:
  /// **'Slut'**
  String get signalCardOver;

  /// No description provided for @signalCardSave.
  ///
  /// In sv, this message translates to:
  /// **'Spara tipset'**
  String get signalCardSave;

  /// No description provided for @signalCardTaxiPays.
  ///
  /// In sv, this message translates to:
  /// **'Taxi betalas'**
  String get signalCardTaxiPays;

  /// No description provided for @signalCardUnsave.
  ///
  /// In sv, this message translates to:
  /// **'Ta bort sparat'**
  String get signalCardUnsave;

  /// No description provided for @signalKindsAgoDays.
  ///
  /// In sv, this message translates to:
  /// **'{days} d'**
  String signalKindsAgoDays(int days);

  /// No description provided for @signalKindsAgoNow.
  ///
  /// In sv, this message translates to:
  /// **'Nu'**
  String get signalKindsAgoNow;

  /// No description provided for @signalKindsCategoryEvent.
  ///
  /// In sv, this message translates to:
  /// **'Event'**
  String get signalKindsCategoryEvent;

  /// No description provided for @signalKindsCategoryFerry.
  ///
  /// In sv, this message translates to:
  /// **'Färja'**
  String get signalKindsCategoryFerry;

  /// No description provided for @signalKindsCategoryFlight.
  ///
  /// In sv, this message translates to:
  /// **'Flyg'**
  String get signalKindsCategoryFlight;

  /// No description provided for @signalKindsCategoryRoad.
  ///
  /// In sv, this message translates to:
  /// **'Väg'**
  String get signalKindsCategoryRoad;

  /// No description provided for @signalKindsCategoryTransit.
  ///
  /// In sv, this message translates to:
  /// **'Tåg & buss'**
  String get signalKindsCategoryTransit;

  /// No description provided for @signalKindsDistanceKm.
  ///
  /// In sv, this message translates to:
  /// **'{km} km'**
  String signalKindsDistanceKm(String km);

  /// No description provided for @signalKindsDistanceMeters.
  ///
  /// In sv, this message translates to:
  /// **'{meters} m'**
  String signalKindsDistanceMeters(int meters);

  /// No description provided for @signalKindsExplainEvent.
  ///
  /// In sv, this message translates to:
  /// **'Match, konsert eller annat. Publiken går hem samtidigt.'**
  String get signalKindsExplainEvent;

  /// No description provided for @signalKindsExplainFerry.
  ///
  /// In sv, this message translates to:
  /// **'Färja på väg in. Folk kliver av i hamnen.'**
  String get signalKindsExplainFerry;

  /// No description provided for @signalKindsExplainFlight.
  ///
  /// In sv, this message translates to:
  /// **'Många flyg landar, eller sista flyget. Folk behöver taxi från flygplatsen.'**
  String get signalKindsExplainFlight;

  /// No description provided for @signalKindsExplainRoad.
  ///
  /// In sv, this message translates to:
  /// **'Trafikolycka. Räkna med kö, eller kör en annan väg.'**
  String get signalKindsExplainRoad;

  /// No description provided for @signalKindsExplainTransit.
  ///
  /// In sv, this message translates to:
  /// **'Tåg, buss eller tunnelbana står still eller är sen. Folk behöver taxi.'**
  String get signalKindsExplainTransit;

  /// No description provided for @signalKindsLongDayRelative.
  ///
  /// In sv, this message translates to:
  /// **'{relative}, {weekday}'**
  String signalKindsLongDayRelative(String relative, String weekday);

  /// No description provided for @signalKindsMeaningHigh.
  ///
  /// In sv, this message translates to:
  /// **'Troligt att folk behöver taxi här.'**
  String get signalKindsMeaningHigh;

  /// No description provided for @signalKindsMeaningLow.
  ///
  /// In sv, this message translates to:
  /// **'Troligen få som behöver taxi här.'**
  String get signalKindsMeaningLow;

  /// No description provided for @signalKindsMeaningMedium.
  ///
  /// In sv, this message translates to:
  /// **'Kan vara värt att följa. Håll koll.'**
  String get signalKindsMeaningMedium;

  /// No description provided for @signalKindsMonthLong.
  ///
  /// In sv, this message translates to:
  /// **'{m, select, m1{januari} m2{februari} m3{mars} m4{april} m5{maj} m6{juni} m7{juli} m8{augusti} m9{september} m10{oktober} m11{november} m12{december} other{}}'**
  String signalKindsMonthLong(String m);

  /// No description provided for @signalKindsRoadClosed.
  ///
  /// In sv, this message translates to:
  /// **'Vägen avstängd'**
  String get signalKindsRoadClosed;

  /// No description provided for @signalKindsRoadHazard.
  ///
  /// In sv, this message translates to:
  /// **'Hinder på vägen'**
  String get signalKindsRoadHazard;

  /// No description provided for @signalKindsRoadMajor.
  ///
  /// In sv, this message translates to:
  /// **'Stor störning'**
  String get signalKindsRoadMajor;

  /// No description provided for @signalKindsToday.
  ///
  /// In sv, this message translates to:
  /// **'I dag'**
  String get signalKindsToday;

  /// No description provided for @signalKindsTomorrow.
  ///
  /// In sv, this message translates to:
  /// **'I morgon'**
  String get signalKindsTomorrow;

  /// No description provided for @signalKindsWeekdayLong.
  ///
  /// In sv, this message translates to:
  /// **'{d, select, d1{måndag} d2{tisdag} d3{onsdag} d4{torsdag} d5{fredag} d6{lördag} d7{söndag} other{}}'**
  String signalKindsWeekdayLong(String d);

  /// No description provided for @signalKindsWeekdayShort.
  ///
  /// In sv, this message translates to:
  /// **'{d, select, d1{mån} d2{tis} d3{ons} d4{tor} d5{fre} d6{lör} d7{sön} other{}}'**
  String signalKindsWeekdayShort(String d);

  /// No description provided for @signalKindsWordAccident.
  ///
  /// In sv, this message translates to:
  /// **'Olycka'**
  String get signalKindsWordAccident;

  /// No description provided for @signalKindsWordBig.
  ///
  /// In sv, this message translates to:
  /// **'Stort'**
  String get signalKindsWordBig;

  /// No description provided for @signalKindsWordMedium.
  ///
  /// In sv, this message translates to:
  /// **'Medel'**
  String get signalKindsWordMedium;

  /// No description provided for @signalKindsWordMiddle.
  ///
  /// In sv, this message translates to:
  /// **'Mellan'**
  String get signalKindsWordMiddle;

  /// No description provided for @signalKindsWordQueue.
  ///
  /// In sv, this message translates to:
  /// **'Kö'**
  String get signalKindsWordQueue;

  /// No description provided for @signalKindsWordSmall.
  ///
  /// In sv, this message translates to:
  /// **'Litet'**
  String get signalKindsWordSmall;

  /// No description provided for @signalKindsWordStrong.
  ///
  /// In sv, this message translates to:
  /// **'Stark'**
  String get signalKindsWordStrong;

  /// No description provided for @signalKindsWordWeak.
  ///
  /// In sv, this message translates to:
  /// **'Svag'**
  String get signalKindsWordWeak;

  /// No description provided for @signalKindsWordWork.
  ///
  /// In sv, this message translates to:
  /// **'Arbete'**
  String get signalKindsWordWork;

  /// No description provided for @signalKindsYesterday.
  ///
  /// In sv, this message translates to:
  /// **'I går'**
  String get signalKindsYesterday;

  /// No description provided for @signalMapCluster.
  ///
  /// In sv, this message translates to:
  /// **'{count} saker här'**
  String signalMapCluster(int count);

  /// No description provided for @signalMapFerry.
  ///
  /// In sv, this message translates to:
  /// **'Färja {name}'**
  String signalMapFerry(String name);

  /// No description provided for @signupScreenBack.
  ///
  /// In sv, this message translates to:
  /// **'Tillbaka'**
  String get signupScreenBack;

  /// No description provided for @signupScreenCompanyHelp.
  ///
  /// In sv, this message translates to:
  /// **'Organisationsnummer behövs inte nu.'**
  String get signupScreenCompanyHelp;

  /// No description provided for @signupScreenCompanyHint.
  ///
  /// In sv, this message translates to:
  /// **'Till exempel Annas Taxi'**
  String get signupScreenCompanyHint;

  /// No description provided for @signupScreenCompanyLabel.
  ///
  /// In sv, this message translates to:
  /// **'Företagets namn'**
  String get signupScreenCompanyLabel;

  /// No description provided for @signupScreenCompanyQuestion.
  ///
  /// In sv, this message translates to:
  /// **'Vad heter företaget?'**
  String get signupScreenCompanyQuestion;

  /// No description provided for @signupScreenCompanyText.
  ///
  /// In sv, this message translates to:
  /// **'Med egna bilar eller förare.'**
  String get signupScreenCompanyText;

  /// No description provided for @signupScreenCompanyTitle.
  ///
  /// In sv, this message translates to:
  /// **'Jag äger ett taxibolag'**
  String get signupScreenCompanyTitle;

  /// No description provided for @signupScreenContinueBankId.
  ///
  /// In sv, this message translates to:
  /// **'Fortsätt med BankID'**
  String get signupScreenContinueBankId;

  /// No description provided for @signupScreenCreateAccount.
  ///
  /// In sv, this message translates to:
  /// **'Skapa kontot'**
  String get signupScreenCreateAccount;

  /// No description provided for @signupScreenDateInvalid.
  ///
  /// In sv, this message translates to:
  /// **'Personnumret har ett datum som inte finns. Kontrollera numret.'**
  String get signupScreenDateInvalid;

  /// No description provided for @signupScreenEmailHelp.
  ///
  /// In sv, this message translates to:
  /// **'Du loggar in med den.'**
  String get signupScreenEmailHelp;

  /// No description provided for @signupScreenEmailLabel.
  ///
  /// In sv, this message translates to:
  /// **'E-post'**
  String get signupScreenEmailLabel;

  /// No description provided for @signupScreenEmailQuestion.
  ///
  /// In sv, this message translates to:
  /// **'Din e-post'**
  String get signupScreenEmailQuestion;

  /// No description provided for @signupScreenHaveAccount.
  ///
  /// In sv, this message translates to:
  /// **'Har du redan ett konto? Logga in'**
  String get signupScreenHaveAccount;

  /// No description provided for @signupScreenKindQuestion.
  ///
  /// In sv, this message translates to:
  /// **'Är du förare eller ägare?'**
  String get signupScreenKindQuestion;

  /// No description provided for @signupScreenKindQuestionNamed.
  ///
  /// In sv, this message translates to:
  /// **'Hej {name}! Är du förare eller ägare?'**
  String signupScreenKindQuestionNamed(String name);

  /// No description provided for @signupScreenLoginInstead.
  ///
  /// In sv, this message translates to:
  /// **'Logga in i stället'**
  String get signupScreenLoginInstead;

  /// No description provided for @signupScreenNext.
  ///
  /// In sv, this message translates to:
  /// **'Nästa'**
  String get signupScreenNext;

  /// No description provided for @signupScreenNotSure.
  ///
  /// In sv, this message translates to:
  /// **'Inte säker? Välj \"Jag är förare\".'**
  String get signupScreenNotSure;

  /// No description provided for @signupScreenPasswordLabel.
  ///
  /// In sv, this message translates to:
  /// **'Lösenord'**
  String get signupScreenPasswordLabel;

  /// No description provided for @signupScreenPasswordMin.
  ///
  /// In sv, this message translates to:
  /// **'Minst 8 tecken'**
  String get signupScreenPasswordMin;

  /// No description provided for @signupScreenPasswordQuestion.
  ///
  /// In sv, this message translates to:
  /// **'Välj ett lösenord'**
  String get signupScreenPasswordQuestion;

  /// No description provided for @signupScreenPhoneLabel.
  ///
  /// In sv, this message translates to:
  /// **'Mobil'**
  String get signupScreenPhoneLabel;

  /// No description provided for @signupScreenPhoneQuestion.
  ///
  /// In sv, this message translates to:
  /// **'Ditt mobilnummer'**
  String get signupScreenPhoneQuestion;

  /// No description provided for @signupScreenProblemChoose.
  ///
  /// In sv, this message translates to:
  /// **'Välj ett av alternativen.'**
  String get signupScreenProblemChoose;

  /// No description provided for @signupScreenProblemCompany.
  ///
  /// In sv, this message translates to:
  /// **'Skriv företagets namn.'**
  String get signupScreenProblemCompany;

  /// No description provided for @signupScreenProblemEmail.
  ///
  /// In sv, this message translates to:
  /// **'Det ser inte ut som en e-postadress. Skriv till exempel namn@gmail.com.'**
  String get signupScreenProblemEmail;

  /// No description provided for @signupScreenProblemPassword.
  ///
  /// In sv, this message translates to:
  /// **'Lösenordet behöver minst 8 tecken.'**
  String get signupScreenProblemPassword;

  /// No description provided for @signupScreenProblemPhone.
  ///
  /// In sv, this message translates to:
  /// **'Det ser inte ut som ett mobilnummer. Skriv till exempel 070 123 45 67.'**
  String get signupScreenProblemPhone;

  /// No description provided for @signupScreenSoloText.
  ///
  /// In sv, this message translates to:
  /// **'Du behöver inget företag.'**
  String get signupScreenSoloText;

  /// No description provided for @signupScreenSoloTitle.
  ///
  /// In sv, this message translates to:
  /// **'Jag är förare'**
  String get signupScreenSoloTitle;

  /// No description provided for @signupScreenSomethingWrong.
  ///
  /// In sv, this message translates to:
  /// **'Något gick fel. Försök igen.'**
  String get signupScreenSomethingWrong;

  /// No description provided for @signupScreenStepOf.
  ///
  /// In sv, this message translates to:
  /// **'Steg {n} av {total}'**
  String signupScreenStepOf(int n, int total);

  /// No description provided for @signupScreenTitle.
  ///
  /// In sv, this message translates to:
  /// **'Prova gratis i en månad'**
  String get signupScreenTitle;

  /// No description provided for @signupScreenUnder18.
  ///
  /// In sv, this message translates to:
  /// **'En enskild firma registreras av någon som fyllt 18. Kontrollera numret.'**
  String get signupScreenUnder18;

  /// No description provided for @supportChatEmptyBody.
  ///
  /// In sv, this message translates to:
  /// **'Skriv din fråga nedan. Du får en notis när vi svarat.'**
  String get supportChatEmptyBody;

  /// No description provided for @supportChatEmptyTitle.
  ///
  /// In sv, this message translates to:
  /// **'Hur kan vi hjälpa till?'**
  String get supportChatEmptyTitle;

  /// No description provided for @supportChatHint.
  ///
  /// In sv, this message translates to:
  /// **'Skriv ett meddelande'**
  String get supportChatHint;

  /// No description provided for @supportChatLoadFailed.
  ///
  /// In sv, this message translates to:
  /// **'Kunde inte hämta chatten. Kontrollera nätet.'**
  String get supportChatLoadFailed;

  /// No description provided for @supportChatRetry.
  ///
  /// In sv, this message translates to:
  /// **'Försök igen'**
  String get supportChatRetry;

  /// No description provided for @supportChatSend.
  ///
  /// In sv, this message translates to:
  /// **'Skicka'**
  String get supportChatSend;

  /// No description provided for @supportChatSendFailed.
  ///
  /// In sv, this message translates to:
  /// **'Meddelandet skickades inte. Försök igen.'**
  String get supportChatSendFailed;

  /// No description provided for @supportChatSubtitle.
  ///
  /// In sv, this message translates to:
  /// **'Vi svarar så snart vi kan'**
  String get supportChatSubtitle;

  /// No description provided for @supportChatTitle.
  ///
  /// In sv, this message translates to:
  /// **'Support'**
  String get supportChatTitle;

  /// No description provided for @tipDetailPartsChipCancelled.
  ///
  /// In sv, this message translates to:
  /// **'INSTÄLLD'**
  String get tipDetailPartsChipCancelled;

  /// No description provided for @tipDetailPartsChipDelayed.
  ///
  /// In sv, this message translates to:
  /// **'FÖRSENAD'**
  String get tipDetailPartsChipDelayed;

  /// No description provided for @tipDetailPartsChipDelayedBy.
  ///
  /// In sv, this message translates to:
  /// **'FÖRSENAD {delay}'**
  String tipDetailPartsChipDelayedBy(String delay);

  /// No description provided for @tipDetailPartsNewClock.
  ///
  /// In sv, this message translates to:
  /// **'→ {clock}'**
  String tipDetailPartsNewClock(String clock);

  /// No description provided for @tipReportCancel.
  ///
  /// In sv, this message translates to:
  /// **'Avbryt'**
  String get tipReportCancel;

  /// No description provided for @tipReportFailed.
  ///
  /// In sv, this message translates to:
  /// **'Kunde inte skicka rapporten. Prova igen.'**
  String get tipReportFailed;

  /// No description provided for @tipReportHint.
  ///
  /// In sv, this message translates to:
  /// **'Valfri förklaring'**
  String get tipReportHint;

  /// No description provided for @tipReportIntro.
  ///
  /// In sv, this message translates to:
  /// **'Berätta kort vad som inte stämmer, till exempel fel plats eller att störningen redan är löst.'**
  String get tipReportIntro;

  /// No description provided for @tipReportReceived.
  ///
  /// In sv, this message translates to:
  /// **'Rapport mottagen — tack.'**
  String get tipReportReceived;

  /// No description provided for @tipReportSend.
  ///
  /// In sv, this message translates to:
  /// **'Skicka rapport'**
  String get tipReportSend;

  /// No description provided for @tipReportThanks.
  ///
  /// In sv, this message translates to:
  /// **'Tack — vi granskar tipset.'**
  String get tipReportThanks;

  /// No description provided for @tipReportTitle.
  ///
  /// In sv, this message translates to:
  /// **'Rapportera felaktigt tips'**
  String get tipReportTitle;

  /// No description provided for @tipSheetAffectedParty.
  ///
  /// In sv, this message translates to:
  /// **'Berörd part: {party}'**
  String tipSheetAffectedParty(String party);

  /// No description provided for @tipSheetAlternativeTraffic.
  ///
  /// In sv, this message translates to:
  /// **'Alternativ trafik'**
  String get tipSheetAlternativeTraffic;

  /// No description provided for @tipSheetCircumstances.
  ///
  /// In sv, this message translates to:
  /// **'Särskilda omständigheter'**
  String get tipSheetCircumstances;

  /// No description provided for @tipSheetClockAt.
  ///
  /// In sv, this message translates to:
  /// **'kl {clock}'**
  String tipSheetClockAt(String clock);

  /// No description provided for @tipSheetClose.
  ///
  /// In sv, this message translates to:
  /// **'Stäng'**
  String get tipSheetClose;

  /// No description provided for @tipSheetCompensationDisclaimer.
  ///
  /// In sv, this message translates to:
  /// **'Beloppet gäller när trafikbolagets villkor är uppfyllda. Vi kan inte bedöma den enskilda resan.'**
  String get tipSheetCompensationDisclaimer;

  /// No description provided for @tipSheetCompensationLink.
  ///
  /// In sv, this message translates to:
  /// **'Läs reglerna hos {operator}'**
  String tipSheetCompensationLink(String operator);

  /// No description provided for @tipSheetCompensationTitle.
  ///
  /// In sv, this message translates to:
  /// **'Taxiersättning'**
  String get tipSheetCompensationTitle;

  /// No description provided for @tipSheetDriveThere.
  ///
  /// In sv, this message translates to:
  /// **'Kör dit'**
  String get tipSheetDriveThere;

  /// No description provided for @tipSheetEnded.
  ///
  /// In sv, this message translates to:
  /// **'Slut'**
  String get tipSheetEnded;

  /// No description provided for @tipSheetEndedAgo.
  ///
  /// In sv, this message translates to:
  /// **'Tog slut för {span} sedan'**
  String tipSheetEndedAgo(String span);

  /// No description provided for @tipSheetEndedBanner.
  ///
  /// In sv, this message translates to:
  /// **'Slut. Tipset gäller inte längre.'**
  String get tipSheetEndedBanner;

  /// No description provided for @tipSheetEndedJustNow.
  ///
  /// In sv, this message translates to:
  /// **'Tog slut nyss'**
  String get tipSheetEndedJustNow;

  /// No description provided for @tipSheetGotFare.
  ///
  /// In sv, this message translates to:
  /// **'Fick körning'**
  String get tipSheetGotFare;

  /// No description provided for @tipSheetHide.
  ///
  /// In sv, this message translates to:
  /// **'Dölj'**
  String get tipSheetHide;

  /// No description provided for @tipSheetLineTo.
  ///
  /// In sv, this message translates to:
  /// **'{line} → {to}'**
  String tipSheetLineTo(String line, String to);

  /// No description provided for @tipSheetMinorNote.
  ///
  /// In sv, this message translates to:
  /// **'Allmänt meddelande. Vi bedömer inte om det är värt att köra dit.'**
  String get tipSheetMinorNote;

  /// No description provided for @tipSheetNavFailed.
  ///
  /// In sv, this message translates to:
  /// **'Kunde inte öppna navigeringen.'**
  String get tipSheetNavFailed;

  /// No description provided for @tipSheetNoCustomer.
  ///
  /// In sv, this message translates to:
  /// **'Ingen kund'**
  String get tipSheetNoCustomer;

  /// No description provided for @tipSheetNoDescription.
  ///
  /// In sv, this message translates to:
  /// **'Ingen ytterligare beskrivning tillgänglig.'**
  String get tipSheetNoDescription;

  /// No description provided for @tipSheetOpenNavigation.
  ///
  /// In sv, this message translates to:
  /// **'Öppna navigering'**
  String get tipSheetOpenNavigation;

  /// No description provided for @tipSheetOperatorFallback.
  ///
  /// In sv, this message translates to:
  /// **'trafikbolaget'**
  String get tipSheetOperatorFallback;

  /// No description provided for @tipSheetReadMore.
  ///
  /// In sv, this message translates to:
  /// **'Läs mer'**
  String get tipSheetReadMore;

  /// No description provided for @tipSheetReported.
  ///
  /// In sv, this message translates to:
  /// **'Rapporterat'**
  String get tipSheetReported;

  /// No description provided for @tipSheetRoadAdvice.
  ///
  /// In sv, this message translates to:
  /// **'Räkna med kö, eller välj en annan väg.'**
  String get tipSheetRoadAdvice;

  /// No description provided for @tipSheetSave.
  ///
  /// In sv, this message translates to:
  /// **'Spara tipset'**
  String get tipSheetSave;

  /// No description provided for @tipSheetSectionEvent.
  ///
  /// In sv, this message translates to:
  /// **'Händelse & beskrivning'**
  String get tipSheetSectionEvent;

  /// No description provided for @tipSheetSectionNotice.
  ///
  /// In sv, this message translates to:
  /// **'Trafikbolagets meddelande'**
  String get tipSheetSectionNotice;

  /// No description provided for @tipSheetSectionRoad.
  ///
  /// In sv, this message translates to:
  /// **'Vägen dit'**
  String get tipSheetSectionRoad;

  /// No description provided for @tipSheetShowAllReasons.
  ///
  /// In sv, this message translates to:
  /// **'Visa alla skäl'**
  String get tipSheetShowAllReasons;

  /// No description provided for @tipSheetShowFewerReasons.
  ///
  /// In sv, this message translates to:
  /// **'Visa färre skäl'**
  String get tipSheetShowFewerReasons;

  /// No description provided for @tipSheetShowFullText.
  ///
  /// In sv, this message translates to:
  /// **'Visa hela texten'**
  String get tipSheetShowFullText;

  /// No description provided for @tipSheetShowLess.
  ///
  /// In sv, this message translates to:
  /// **'Visa mindre'**
  String get tipSheetShowLess;

  /// No description provided for @tipSheetSourcePage.
  ///
  /// In sv, this message translates to:
  /// **'Trafikbolagets sida'**
  String get tipSheetSourcePage;

  /// No description provided for @tipSheetStartedAgo.
  ///
  /// In sv, this message translates to:
  /// **'Började för {span} sedan'**
  String tipSheetStartedAgo(String span);

  /// No description provided for @tipSheetStartedJustNow.
  ///
  /// In sv, this message translates to:
  /// **'Började nyss'**
  String get tipSheetStartedJustNow;

  /// No description provided for @tipSheetStartsIn.
  ///
  /// In sv, this message translates to:
  /// **'Börjar om {span}'**
  String tipSheetStartsIn(String span);

  /// No description provided for @tipSheetStartsNow.
  ///
  /// In sv, this message translates to:
  /// **'Börjar nu'**
  String get tipSheetStartsNow;

  /// No description provided for @tipSheetStatusNotice.
  ///
  /// In sv, this message translates to:
  /// **'MEDDELANDE'**
  String get tipSheetStatusNotice;

  /// No description provided for @tipSheetStatusStopped.
  ///
  /// In sv, this message translates to:
  /// **'STOPP I TRAFIKEN'**
  String get tipSheetStatusStopped;

  /// No description provided for @tipSheetTaxiPaid.
  ///
  /// In sv, this message translates to:
  /// **'Taxi betalas'**
  String get tipSheetTaxiPaid;

  /// No description provided for @tipSheetUnsave.
  ///
  /// In sv, this message translates to:
  /// **'Ta bort sparat'**
  String get tipSheetUnsave;

  /// No description provided for @trialWelcomeAllIncluded.
  ///
  /// In sv, this message translates to:
  /// **'Allt ingår just nu.'**
  String get trialWelcomeAllIncluded;

  /// No description provided for @trialWelcomeClose.
  ///
  /// In sv, this message translates to:
  /// **'Stäng'**
  String get trialWelcomeClose;

  /// No description provided for @trialWelcomeColorNote.
  ///
  /// In sv, this message translates to:
  /// **'Färgen visar hur stark signalen är. En stark signal betyder att många sannolikt behöver taxi.'**
  String get trialWelcomeColorNote;

  /// No description provided for @trialWelcomeCostsNothing.
  ///
  /// In sv, this message translates to:
  /// **'Det kostar inget att prova.'**
  String get trialWelcomeCostsNothing;

  /// Datum utan år, t.ex. "29 december"
  ///
  /// In sv, this message translates to:
  /// **'{day} {month, select, 1{januari} 2{februari} 3{mars} 4{april} 5{maj} 6{juni} 7{juli} 8{augusti} 9{september} 10{oktober} 11{november} 12{december} other{}}'**
  String trialWelcomeDate(int day, String month);

  /// No description provided for @trialWelcomeDone.
  ///
  /// In sv, this message translates to:
  /// **'Klar'**
  String get trialWelcomeDone;

  /// No description provided for @trialWelcomeFreeDays.
  ///
  /// In sv, this message translates to:
  /// **'{days, plural, one{Gratis i {days} dag.} other{Gratis i {days} dagar.}}'**
  String trialWelcomeFreeDays(int days);

  /// No description provided for @trialWelcomeFreeToTry.
  ///
  /// In sv, this message translates to:
  /// **'Gratis att prova.'**
  String get trialWelcomeFreeToTry;

  /// No description provided for @trialWelcomeFreeUntil.
  ///
  /// In sv, this message translates to:
  /// **'Gratis till {date}.'**
  String trialWelcomeFreeUntil(String date);

  /// No description provided for @trialWelcomeIncludedHeading.
  ///
  /// In sv, this message translates to:
  /// **'Ingår i provet'**
  String get trialWelcomeIncludedHeading;

  /// No description provided for @trialWelcomeIncludedTitle.
  ///
  /// In sv, this message translates to:
  /// **'Vad ingår i provet?'**
  String get trialWelcomeIncludedTitle;

  /// No description provided for @trialWelcomeIncludedUnknown.
  ///
  /// In sv, this message translates to:
  /// **'Det som ingår i provet ser du i appen. Det som inte ingår har ett lås.'**
  String get trialWelcomeIncludedUnknown;

  /// No description provided for @trialWelcomeLineEvent.
  ///
  /// In sv, this message translates to:
  /// **'Event som slutar: match, konsert eller annat.'**
  String get trialWelcomeLineEvent;

  /// No description provided for @trialWelcomeLineFerry.
  ///
  /// In sv, this message translates to:
  /// **'Färjor som lägger till i hamnen.'**
  String get trialWelcomeLineFerry;

  /// No description provided for @trialWelcomeLineFlight.
  ///
  /// In sv, this message translates to:
  /// **'Flyg som är sena, eller när många flyg landar.'**
  String get trialWelcomeLineFlight;

  /// No description provided for @trialWelcomeLineRoad.
  ///
  /// In sv, this message translates to:
  /// **'Trafikolyckor som stoppar trafiken.'**
  String get trialWelcomeLineRoad;

  /// No description provided for @trialWelcomeLineTransit.
  ///
  /// In sv, this message translates to:
  /// **'Tåg och buss som är sena eller inställda. Sista avgången.'**
  String get trialWelcomeLineTransit;

  /// No description provided for @trialWelcomeNeedsMembership.
  ///
  /// In sv, this message translates to:
  /// **'Det kräver medlemskap. {onWeb}'**
  String trialWelcomeNeedsMembership(String onWeb);

  /// No description provided for @trialWelcomeNext.
  ///
  /// In sv, this message translates to:
  /// **'Nästa'**
  String get trialWelcomeNext;

  /// No description provided for @trialWelcomeOneSeat.
  ///
  /// In sv, this message translates to:
  /// **'Du kan ha 1 plats i provet, med ett län.'**
  String get trialWelcomeOneSeat;

  /// No description provided for @trialWelcomePageOf.
  ///
  /// In sv, this message translates to:
  /// **'Sida {page} av {total}'**
  String trialWelcomePageOf(int page, int total);

  /// No description provided for @trialWelcomeReadyTitle.
  ///
  /// In sv, this message translates to:
  /// **'Klart! Du är igång'**
  String get trialWelcomeReadyTitle;

  /// No description provided for @trialWelcomeSeats.
  ///
  /// In sv, this message translates to:
  /// **'{limit, plural, other{Du kan ha upp till {limit} platser i provet.}}'**
  String trialWelcomeSeats(int limit);

  /// No description provided for @trialWelcomeShowTips.
  ///
  /// In sv, this message translates to:
  /// **'Visa tipsen'**
  String get trialWelcomeShowTips;

  /// No description provided for @trialWelcomeSkip.
  ///
  /// In sv, this message translates to:
  /// **'Hoppa över'**
  String get trialWelcomeSkip;

  /// No description provided for @trialWelcomeStep1Text.
  ///
  /// In sv, this message translates to:
  /// **'Öppna Inställningar och tryck på Dina län. Länet styr vilka tips du får.'**
  String get trialWelcomeStep1Text;

  /// No description provided for @trialWelcomeStep1Title.
  ///
  /// In sv, this message translates to:
  /// **'Byt län'**
  String get trialWelcomeStep1Title;

  /// No description provided for @trialWelcomeStep2Text.
  ///
  /// In sv, this message translates to:
  /// **'Inbjudan skickas av företagets administratör på webben, inte från appen. Föraren får ett mejl, väljer ett lösenord och loggar in i appen med e-post och lösenord.'**
  String get trialWelcomeStep2Text;

  /// No description provided for @trialWelcomeStep2Title.
  ///
  /// In sv, this message translates to:
  /// **'Har du ett taxibolag? Bjud in förare på webben'**
  String get trialWelcomeStep2Title;

  /// No description provided for @trialWelcomeStepsTitle.
  ///
  /// In sv, this message translates to:
  /// **'Så kommer du igång'**
  String get trialWelcomeStepsTitle;

  /// No description provided for @trialWelcomeTrialEnded.
  ///
  /// In sv, this message translates to:
  /// **'Provet är slut. {onWeb}'**
  String trialWelcomeTrialEnded(String onWeb);

  /// No description provided for @trialWelcomeTrialRunning.
  ///
  /// In sv, this message translates to:
  /// **'Provet pågår. Det gäller till {date}.'**
  String trialWelcomeTrialRunning(String date);

  /// No description provided for @trialWelcomeTrialStarts.
  ///
  /// In sv, this message translates to:
  /// **'Provet startar när första föraren loggar in.'**
  String get trialWelcomeTrialStarts;

  /// No description provided for @trialWelcomeTrialStartsPending.
  ///
  /// In sv, this message translates to:
  /// **'Provet startar när första föraren loggar in. Tills dess går ingen tid.'**
  String get trialWelcomeTrialStartsPending;

  /// No description provided for @trialWelcomeTrialTitleDays.
  ///
  /// In sv, this message translates to:
  /// **'{days, plural, one{Du provar gratis i {days} dag} other{Du provar gratis i {days} dagar}}'**
  String trialWelcomeTrialTitleDays(int days);

  /// No description provided for @trialWelcomeTrialTitleNoDays.
  ///
  /// In sv, this message translates to:
  /// **'Du provar gratis'**
  String get trialWelcomeTrialTitleNoDays;

  /// No description provided for @trialWelcomeWatching.
  ///
  /// In sv, this message translates to:
  /// **'Vi bevakar'**
  String get trialWelcomeWatching;

  /// No description provided for @trialWelcomeWhatBody.
  ///
  /// In sv, this message translates to:
  /// **'Taxi Tips visar var folk kan behöva taxi just nu. Det är tips, inte löften. Du bestämmer själv om det är värt att åka.'**
  String get trialWelcomeWhatBody;

  /// No description provided for @trialWelcomeWhatTitle.
  ///
  /// In sv, this message translates to:
  /// **'Välkommen till Taxi Tips'**
  String get trialWelcomeWhatTitle;

  /// No description provided for @vehicleSessionAnotherPhone.
  ///
  /// In sv, this message translates to:
  /// **'en annan telefon'**
  String get vehicleSessionAnotherPhone;

  /// No description provided for @vehicleSessionCancel.
  ///
  /// In sv, this message translates to:
  /// **'Avbryt'**
  String get vehicleSessionCancel;

  /// No description provided for @vehicleSessionCar.
  ///
  /// In sv, this message translates to:
  /// **'Bil'**
  String get vehicleSessionCar;

  /// No description provided for @vehicleSessionCountiesCount.
  ///
  /// In sv, this message translates to:
  /// **'{count} län'**
  String vehicleSessionCountiesCount(int count);

  /// No description provided for @vehicleSessionDrive.
  ///
  /// In sv, this message translates to:
  /// **'Kör'**
  String get vehicleSessionDrive;

  /// No description provided for @vehicleSessionLeave.
  ///
  /// In sv, this message translates to:
  /// **'Lämna bilen'**
  String get vehicleSessionLeave;

  /// No description provided for @vehicleSessionNoVehicles.
  ///
  /// In sv, this message translates to:
  /// **'Telefonen är inte kopplad till någon bil. Be din chef bjuda in dig med din e-post, och logga in som förare.'**
  String get vehicleSessionNoVehicles;

  /// No description provided for @vehicleSessionSubtitle.
  ///
  /// In sv, this message translates to:
  /// **'Tipsen gäller bilens län. En bil kan bara ha en telefon åt gången.'**
  String get vehicleSessionSubtitle;

  /// No description provided for @vehicleSessionTakeOver.
  ///
  /// In sv, this message translates to:
  /// **'Ta över'**
  String get vehicleSessionTakeOver;

  /// No description provided for @vehicleSessionTakeOverBody.
  ///
  /// In sv, this message translates to:
  /// **'{message}\n\nDen andra telefonen slutar visa tips för den här bilen direkt.'**
  String vehicleSessionTakeOverBody(String message);

  /// No description provided for @vehicleSessionTakeOverCar.
  ///
  /// In sv, this message translates to:
  /// **'Ta över bilen'**
  String get vehicleSessionTakeOverCar;

  /// No description provided for @vehicleSessionTakeOverTitle.
  ///
  /// In sv, this message translates to:
  /// **'Ta över {plate}?'**
  String vehicleSessionTakeOverTitle(String plate);

  /// No description provided for @vehicleSessionTheCar.
  ///
  /// In sv, this message translates to:
  /// **'bilen'**
  String get vehicleSessionTheCar;

  /// No description provided for @vehicleSessionTitle.
  ///
  /// In sv, this message translates to:
  /// **'Vilken bil kör du?'**
  String get vehicleSessionTitle;

  /// No description provided for @vehicleSessionUsedBy.
  ///
  /// In sv, this message translates to:
  /// **'Används av {name}'**
  String vehicleSessionUsedBy(String name);

  /// No description provided for @vehicleSessionYouDriveThis.
  ///
  /// In sv, this message translates to:
  /// **'Du kör den här'**
  String get vehicleSessionYouDriveThis;

  /// No description provided for @welcomeScreenBrowserFailed.
  ///
  /// In sv, this message translates to:
  /// **'Kunde inte öppna webbläsaren'**
  String get welcomeScreenBrowserFailed;

  /// No description provided for @welcomeScreenCreateAccount.
  ///
  /// In sv, this message translates to:
  /// **'Skapa konto gratis'**
  String get welcomeScreenCreateAccount;

  /// Huvudrubrik på välkomstskärmen
  ///
  /// In sv, this message translates to:
  /// **'Se var folk behöver taxi'**
  String get welcomeScreenHeadline;

  /// No description provided for @welcomeScreenLogin.
  ///
  /// In sv, this message translates to:
  /// **'Logga in'**
  String get welcomeScreenLogin;

  /// No description provided for @welcomeScreenSeeDemo.
  ///
  /// In sv, this message translates to:
  /// **'Se demon på webben'**
  String get welcomeScreenSeeDemo;
}

class _AppLocalizationsDelegate
    extends LocalizationsDelegate<AppLocalizations> {
  const _AppLocalizationsDelegate();

  @override
  Future<AppLocalizations> load(Locale locale) {
    return SynchronousFuture<AppLocalizations>(lookupAppLocalizations(locale));
  }

  @override
  bool isSupported(Locale locale) =>
      <String>['ar', 'en', 'sv'].contains(locale.languageCode);

  @override
  bool shouldReload(_AppLocalizationsDelegate old) => false;
}

AppLocalizations lookupAppLocalizations(Locale locale) {
  // Lookup logic when only language code is specified.
  switch (locale.languageCode) {
    case 'ar':
      return AppLocalizationsAr();
    case 'en':
      return AppLocalizationsEn();
    case 'sv':
      return AppLocalizationsSv();
  }

  throw FlutterError(
    'AppLocalizations.delegate failed to load unsupported locale "$locale". This is likely '
    'an issue with the localizations generation tool. Please file an issue '
    'on GitHub with a reproducible sample app and the gen-l10n configuration '
    'that was used.',
  );
}
