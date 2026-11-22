// ignore: unused_import
import 'package:intl/intl.dart' as intl;
import 'app_localizations.dart';

// ignore_for_file: type=lint

/// The translations for Swedish (`sv`).
class AppLocalizationsSv extends AppLocalizations {
  AppLocalizationsSv([String locale = 'sv']) : super(locale);

  @override
  String get alertFeedbackGotFare => 'Fick körning';

  @override
  String get alertFeedbackNoCustomer => 'Ingen kund';

  @override
  String get alertFeedbackQueued => 'Sparat. Skickas när du har nät.';

  @override
  String get alertFeedbackSaveFailed => 'Kunde inte spara svaret. Försök igen.';

  @override
  String get alertFeedbackThanks => 'Tack!';

  @override
  String get alertFeedbackTitle => 'Hur gick det?';

  @override
  String get apiClientAccountCreatedOffline =>
      'Kontot är skapat, men vi nådde inte servern. Logga in när du har nät igen.';

  @override
  String apiClientAuthError(String details) {
    return 'Auth-fel: $details';
  }

  @override
  String get apiClientBankIdUnavailable =>
      'BankID är inte tillgängligt just nu.';

  @override
  String get apiClientBaseUrlMissing =>
      'API_BASE_URL är inte satt. Parkoppling och bilval kräver TaxiTips-backenden.';

  @override
  String get apiClientCannotDeleteAccount =>
      'Det går inte att radera kontot just nu. Försök igen senare.';

  @override
  String get apiClientCouldNotCreateAccount => 'Kunde inte skapa konto';

  @override
  String apiClientDatabaseError(String details) {
    return 'Databasfel: $details';
  }

  @override
  String get apiClientFavoritesNeedBackend =>
      'Favoriter kräver Django-backenden';

  @override
  String get apiClientInvalidTransferCode => 'Ogiltig byteskod';

  @override
  String get apiClientInvalidVerificationCode => 'Verifieringskoden är ogiltig';

  @override
  String get apiClientLoginFailed => 'Det gick inte att logga in. Försök igen.';

  @override
  String get apiClientLoginRequired => 'Logga in för att fortsätta.';

  @override
  String get apiClientNoCompany => 'Inget bolag';

  @override
  String get apiClientNoDevice => 'Ingen enhet';

  @override
  String get apiClientNoDeviceKey => 'Servern gav ingen enhetsnyckel.';

  @override
  String get apiClientNoDevicePush =>
      'Ingen enhet — logga in via backend för push';

  @override
  String get apiClientNoDeviceToName => 'Ingen enhet att namnge.';

  @override
  String get apiClientNoValidSession =>
      'Inloggningen gav ingen giltig session.';

  @override
  String get apiClientNotLoggedIn => 'Inte inloggad';

  @override
  String get apiClientNotifyLineDelayedHelp =>
      'Vanligtvis en svag signal -- av som standard.';

  @override
  String get apiClientNotifyLineDelayedLabel => 'Förseningar';

  @override
  String get apiClientNotifyLineDelayedShort => 'Linjen kör, men försenad';

  @override
  String get apiClientNotifyLinePausedHelp =>
      'Störst chans att det finns folk som behöver taxi.';

  @override
  String get apiClientNotifyLinePausedLabel => 'Hela linjen står stilla';

  @override
  String get apiClientNotifyLinePausedShort => 'Ingen trafik alls på linjen';

  @override
  String get apiClientNotifyNeedsServer =>
      'Notisvalen kräver TaxiTips-servern.';

  @override
  String get apiClientNotifyRoadAccidentHelp =>
      'Påverkar mest bilister redan på väg, men värt att veta om.';

  @override
  String get apiClientNotifyRoadAccidentLabel => 'Olycka eller avstängd väg';

  @override
  String get apiClientNotifyRoadShort => 'Vägtrafik';

  @override
  String get apiClientNotifyRoadWorkHelp =>
      'Sällan en taxisignal -- av som standard.';

  @override
  String get apiClientNotifyRoadWorkLabel => 'Vägarbete eller köbildning';

  @override
  String get apiClientNotifyVehicleCancelledHelp =>
      'Färre påverkade, men kan ändå vara värt en titt.';

  @override
  String get apiClientNotifyVehicleCancelledLabel => 'Enstaka avgång inställd';

  @override
  String get apiClientNotifyVehicleCancelledShort =>
      'En avgång inställd, andra går som vanligt';

  @override
  String get apiClientOnDutyNeedsBackend => 'I tjänst kräver den nya backenden';

  @override
  String get apiClientPhoneNotPaired => 'Telefonen är inte parkopplad.';

  @override
  String get apiClientSupportChatUnavailable =>
      'Supportchatten är inte tillgänglig här.';

  @override
  String get appMainLogout => 'Logga ut';

  @override
  String get appMainSomethingWrong => 'Något gick fel.';

  @override
  String get appMainTrialNotStarted =>
      'Kontot är skapat men provet kunde inte starta. Kontakta TaxiTips.';

  @override
  String get appMainTryAgain => 'Försök igen';

  @override
  String get bankIdFlowAppNotFound =>
      'Vi hittar inte BankID-appen på den här telefonen. Skanna koden med BankID på en annan telefon.';

  @override
  String get bankIdFlowApproveInApp =>
      'Godkänn i BankID-appen. Kom sedan tillbaka hit.';

  @override
  String get bankIdFlowBadEmail => 'Fel e-post.';

  @override
  String get bankIdFlowCancel => 'Avbryt';

  @override
  String get bankIdFlowChangeEmail => 'Byt e-post också';

  @override
  String get bankIdFlowFailed => 'Legitimeringen misslyckades. Försök igen.';

  @override
  String bankIdFlowHello(String name) {
    return 'Hej $name!';
  }

  @override
  String get bankIdFlowHidePassword => 'Dölj lösenord';

  @override
  String get bankIdFlowNewEmail => 'Ny e-post';

  @override
  String get bankIdFlowNewPasswordTitle => 'Nytt lösenord';

  @override
  String get bankIdFlowNoAccountHelp =>
      'Ditt BankID har inget konto här.\n\nFick du en inbjudan från ditt taxibolag? Be dem skicka inbjudan igen. Då får du ett mejl där du väljer ett nytt lösenord.\n\nHar du inget konto? Tryck på Skapa konto.';

  @override
  String get bankIdFlowNoAccountTitle => 'Vi hittar inget konto';

  @override
  String get bankIdFlowNoResponse => 'BankID svarar inte just nu. Försök igen.';

  @override
  String get bankIdFlowOk => 'OK';

  @override
  String get bankIdFlowOpenBankId => 'Öppna BankID';

  @override
  String get bankIdFlowOtherPhone => 'BankID på en annan telefon';

  @override
  String get bankIdFlowPasswordHelper => 'Minst 8 tecken';

  @override
  String get bankIdFlowPasswordMin => 'Lösenordet: minst 8 tecken.';

  @override
  String get bankIdFlowQrLabel => 'QR-kod för BankID';

  @override
  String get bankIdFlowSave => 'Spara';

  @override
  String get bankIdFlowScanOnOther =>
      'Öppna BankID på din andra telefon och skanna koden.';

  @override
  String get bankIdFlowShowPassword => 'Visa lösenord';

  @override
  String get bankIdFlowSomethingWrong => 'Något gick fel. Försök igen.';

  @override
  String get bankIdFlowThisPhone => 'BankID på den här telefonen';

  @override
  String get bankIdFlowTooLong => 'Det tog för lång tid. Försök igen.';

  @override
  String get bankIdFlowTryAgain => 'Försök igen';

  @override
  String get bankIdFlowYourAccount => 'Ditt konto:';

  @override
  String get categoryBarAll => 'Alla';

  @override
  String get categoryBarSaved => 'Sparat';

  @override
  String get companySettingsActiveTitle => 'Aktivt';

  @override
  String get companySettingsAdd => 'Lägg till';

  @override
  String get companySettingsAddCar => 'Lägg till bil';

  @override
  String get companySettingsAlreadyConnected => 'Redan kopplad';

  @override
  String get companySettingsBlock => 'Spärra';

  @override
  String get companySettingsBlockBody =>
      'Telefonen slutar visa tips direkt och lämnar bilen. Föraren behöver en ny inbjudan för att komma in igen.';

  @override
  String get companySettingsBlockPhone => 'Spärra telefonen';

  @override
  String companySettingsBlockTitle(String label) {
    return 'Spärra $label?';
  }

  @override
  String get companySettingsCancel => 'Avbryt';

  @override
  String get companySettingsCar => 'Bil';

  @override
  String companySettingsCarAdded(String plate) {
    return '$plate är tillagd';
  }

  @override
  String get companySettingsCarMissingOnLicense =>
      'Bilen saknas på licensen. Kontakta support.';

  @override
  String companySettingsCarRemoved(String plate) {
    return '$plate är borttagen';
  }

  @override
  String companySettingsCars(int used, int limit) {
    String _temp0 = intl.Intl.pluralLogic(
      limit,
      locale: localeName,
      other: 'bilar',
      one: 'bil',
    );
    return '$used av $_temp0';
  }

  @override
  String get companySettingsCarsLabel => 'Bilar';

  @override
  String companySettingsChangeAgainNextMonth(String label) {
    return '$label\nDu kan byta län igen nästa månad.';
  }

  @override
  String companySettingsChangeUsesOne(String label) {
    return '$label. Ett byte använder ett av dem.';
  }

  @override
  String get companySettingsCouldNotReadCompany => 'Kunde inte läsa företaget.';

  @override
  String companySettingsCountyChangesLeft(int remaining, int total) {
    return 'Länbyten kvar den här månaden: $remaining av $total';
  }

  @override
  String get companySettingsCountyNotChangeable =>
      'Länet kan inte bytas i appen.';

  @override
  String get companySettingsCountyWhereCarDrives => 'Län där bilen kör';

  @override
  String companySettingsDaysLeft(int days) {
    return '$days dagar kvar';
  }

  @override
  String get companySettingsDriveMyself => 'Kör själv med den här telefonen';

  @override
  String get companySettingsDriver => 'Förare';

  @override
  String get companySettingsDriverEmail => 'Förarens e-post';

  @override
  String get companySettingsDriverEmailError =>
      'Skriv förarens e-post, t.ex. namn@exempel.se';

  @override
  String get companySettingsDriverName => 'Förarens namn';

  @override
  String get companySettingsDriverNameOptional => 'Förarens namn (frivilligt)';

  @override
  String get companySettingsDrivers => 'Förare';

  @override
  String companySettingsDriversCount(int count) {
    return '$count förare';
  }

  @override
  String companySettingsDrivingBy(String name) {
    return 'Kör: $name';
  }

  @override
  String get companySettingsDrivingNow => 'Kör nu';

  @override
  String companySettingsGraceLine(String date) {
    return 'Tipsen fungerar till $date.';
  }

  @override
  String get companySettingsGraceTitle => 'Medlemskap pausas snart';

  @override
  String get companySettingsInviteByEmail => 'Bjud in förare med e-post';

  @override
  String get companySettingsInviteDriverBody =>
      'Föraren får ett mejl, väljer lösenord och loggar in i appen. Då kopplas telefonen till bilen.';

  @override
  String companySettingsInviteDriverTitle(String plate) {
    return 'Bjud in förare till $plate';
  }

  @override
  String get companySettingsInviteExpired => 'Inbjudan har gått ut';

  @override
  String get companySettingsInviteRemoved => 'Inbjudan är borttagen';

  @override
  String companySettingsInviteResent(String email) {
    return 'Inbjudan skickad igen till $email';
  }

  @override
  String companySettingsInviteSent(String email) {
    return 'Inbjudan skickad till $email';
  }

  @override
  String companySettingsInvitedCount(int count) {
    return '$count inbjuden';
  }

  @override
  String get companySettingsInvitedNotLoggedIn =>
      'Inbjuden · har inte loggat in än';

  @override
  String get companySettingsLastDay => 'Sista dagen';

  @override
  String get companySettingsLoadFailedPull =>
      'Kunde inte läsa företaget just nu. Dra ner för att försöka igen.';

  @override
  String get companySettingsMonthsShort =>
      'jan,feb,mar,apr,maj,jun,jul,aug,sep,okt,nov,dec';

  @override
  String get companySettingsMore => 'Mer';

  @override
  String get companySettingsNameHint => 't.ex. Anna';

  @override
  String get companySettingsNoCars => 'Inga bilar';

  @override
  String get companySettingsNoChangesLeft =>
      'Inga länbyten kvar den här månaden.';

  @override
  String get companySettingsNoCounty => 'Inget län';

  @override
  String get companySettingsNoDriver => 'Ingen förare';

  @override
  String get companySettingsNoDriverConnected => 'Ingen förare kopplad';

  @override
  String companySettingsNowDrives(String plate) {
    return 'Den här telefonen kör nu $plate';
  }

  @override
  String companySettingsNowDrivesIn(String plate, String county) {
    return '$plate kör nu i $county';
  }

  @override
  String get companySettingsOnlyAdminChanges =>
      'Bara en administratör kan byta län.';

  @override
  String companySettingsPairedPickCar(String plate) {
    return 'Telefonen är kopplad till $plate. Välj bilen i listan.';
  }

  @override
  String get companySettingsPausedTitle => 'Pausat';

  @override
  String get companySettingsPhoneBlocked => 'Telefonen är spärrad';

  @override
  String get companySettingsPlateLabel => 'Registreringsnummer';

  @override
  String get companySettingsRemove => 'Ta bort';

  @override
  String get companySettingsRemoveCar => 'Ta bort bilen';

  @override
  String get companySettingsRemoveCarBody =>
      'Förarna i bilen slutar få tips direkt. Platsen i provet blir ledig.';

  @override
  String companySettingsRemoveCarTitle(String plate) {
    return 'Ta bort $plate?';
  }

  @override
  String get companySettingsRename => 'Byt namn';

  @override
  String companySettingsRenewsLine(String date) {
    return 'Förnyas $date';
  }

  @override
  String get companySettingsResendInvite => 'Skicka igen';

  @override
  String get companySettingsRetry => 'Försök igen';

  @override
  String companySettingsRevokeBody(String email) {
    return '$email kan inte längre använda inbjudan för att logga in.';
  }

  @override
  String get companySettingsRevokeInvite => 'Ta bort inbjudan';

  @override
  String get companySettingsRevokeTitle => 'Ta bort inbjudan?';

  @override
  String get companySettingsSave => 'Spara';

  @override
  String get companySettingsSendInvite => 'Skicka inbjudan';

  @override
  String get companySettingsSuspendedLine => 'Kontakta oss i chatten.';

  @override
  String get companySettingsSuspendedTitle => 'Avstängt';

  @override
  String get companySettingsTapToChangeCounty => 'Tryck för att byta län';

  @override
  String get companySettingsTheCar => 'bilen';

  @override
  String get companySettingsThePhone => 'telefonen';

  @override
  String get companySettingsThisPhone => 'Den här telefonen';

  @override
  String get companySettingsTipsPaused => 'Tipsen är pausade.';

  @override
  String get companySettingsTrialAllIncluded =>
      'Allt i appen ingår under provet.';

  @override
  String companySettingsTrialContinuesLine(String until, String cars) {
    return 'Medlemskapet fortsätter efter provet · $until · $cars';
  }

  @override
  String get companySettingsTrialEndedTitle => 'Provet är slut';

  @override
  String companySettingsTrialLine(String until, String cars) {
    return '$until · $cars';
  }

  @override
  String get companySettingsTrialLockedNotIncluded =>
      'Det som har ett lås i appen ingår inte i provet.';

  @override
  String companySettingsTrialPendingLine(String cars) {
    return 'Startar när första telefonen kopplas · $cars';
  }

  @override
  String get companySettingsTrialTitle => 'Provperiod';

  @override
  String companySettingsTrialUntil(String date) {
    return 'Provet gäller till $date.';
  }

  @override
  String get companySettingsWhereDoesCarDrive => 'Var kör bilen?';

  @override
  String get companySettingsYourCompany => 'Ditt företag';

  @override
  String get countyChecklistAllCounties =>
      'Du ser tips från alla län i medlemskapet. Bocka ur dem du inte vill se.';

  @override
  String get countyChecklistChangeTrialCounty => 'Byt provets län';

  @override
  String get countyChecklistDone => 'Klar';

  @override
  String get countyChecklistNoCounties => 'Medlemskapet har inga län än.';

  @override
  String countyChecklistSomeCounties(int selected, int total) {
    return 'Du ser tips från $selected av $total län.';
  }

  @override
  String get countyChecklistTitle => 'Dina län';

  @override
  String get driverScreenAccessInactive => 'Åtkomsten är inte aktiv.';

  @override
  String get driverScreenAllCountiesSelected =>
      'Alla dina län är valda. Bocka ur dem du inte vill se.';

  @override
  String get driverScreenAllTips => 'Alla tips';

  @override
  String driverScreenAllYourCounties(int count) {
    return 'Alla dina län ($count)';
  }

  @override
  String get driverScreenArea => 'Område';

  @override
  String get driverScreenBack => 'Tillbaka';

  @override
  String get driverScreenBlockedBody => 'Kontakta TaxiTips support.';

  @override
  String get driverScreenBlockedTitle => 'Kontot är avstängt';

  @override
  String get driverScreenCalm => 'Lugnt just nu';

  @override
  String get driverScreenCancelled => 'Avbrutet';

  @override
  String driverScreenCategoryLocked(String category) {
    return '$category ingår inte i provet';
  }

  @override
  String get driverScreenChoose => 'Välj';

  @override
  String get driverScreenChooseAreaText =>
      'Välj ditt körområde för att se tips.';

  @override
  String get driverScreenChooseCar => 'Välj vilken bil du kör för att se tips.';

  @override
  String get driverScreenChooseCarAction => 'Välj bil';

  @override
  String get driverScreenChooseCarFirstCounties =>
      'Välj bil först. Då visas bilens län här.';

  @override
  String get driverScreenClear => 'Rensa';

  @override
  String get driverScreenClearFilters => 'Rensa filter';

  @override
  String get driverScreenConnectingPhone => 'Kopplar telefon…';

  @override
  String get driverScreenCountiesAndMunicipalities => 'Län och kommuner';

  @override
  String get driverScreenDayToday => 'I dag';

  @override
  String get driverScreenDayTomorrow => 'I morgon';

  @override
  String get driverScreenDayWeekend => 'Helgen';

  @override
  String driverScreenDays(int count) {
    String _temp0 = intl.Intl.pluralLogic(
      count,
      locale: localeName,
      other: '$count dagar',
    );
    return '$_temp0';
  }

  @override
  String get driverScreenDone => 'Klar';

  @override
  String get driverScreenDrivingArea => 'Körområde';

  @override
  String get driverScreenDrivingAreaText =>
      'Länen du kör i. Notiserna, och listan när appen inte har din plats, följer körområdet.';

  @override
  String get driverScreenEvents => 'Event';

  @override
  String get driverScreenEventsFailed => 'Kan inte hämta event just nu.';

  @override
  String get driverScreenEventsToday => 'Event i dag';

  @override
  String get driverScreenFerries => 'Färjor';

  @override
  String get driverScreenFetchingPosition => 'Hämtar position…';

  @override
  String get driverScreenFilter => 'Filter';

  @override
  String get driverScreenGpsOff =>
      'Slå på plats (GPS) i telefonens inställningar';

  @override
  String get driverScreenGpsTimeout =>
      'GPS tog för lång tid — försök utomhus eller igen';

  @override
  String get driverScreenGroupMedium => 'Medel';

  @override
  String get driverScreenGroupOther => 'Övrigt';

  @override
  String get driverScreenGroupStrong => 'Starka';

  @override
  String driverScreenGroupTitle(String name, int count) {
    return '$name · $count';
  }

  @override
  String get driverScreenGroupWeak => 'Svaga';

  @override
  String driverScreenHidden(String types) {
    return 'Dolt: $types';
  }

  @override
  String driverScreenHiddenTiers(int count) {
    String _temp0 = intl.Intl.pluralLogic(
      count,
      locale: localeName,
      other: '$count störningstyper dolda',
    );
    return '$_temp0';
  }

  @override
  String get driverScreenHistory => 'Historik';

  @override
  String driverScreenKm(int km) {
    return '$km km';
  }

  @override
  String get driverScreenLegend => 'Vad betyder symbolerna?';

  @override
  String get driverScreenLocationAllow =>
      'Tillåt plats för TaxiTips i telefonens inställningar';

  @override
  String get driverScreenLocationDenied => 'Platsbehörighet nekades';

  @override
  String get driverScreenLocationTimeout => 'Plats tog för lång tid';

  @override
  String driverScreenLockedCount(int count) {
    String _temp0 = intl.Intl.pluralLogic(
      count,
      locale: localeName,
      other: 'Just nu finns $count sådana tips i ditt område.',
      one: 'Just nu finns 1 sådant tips i ditt område.',
    );
    return '$_temp0';
  }

  @override
  String get driverScreenLoginInvalid =>
      'Inloggningen fungerar inte. Logga in igen.';

  @override
  String get driverScreenMoreDates => 'Fler datum';

  @override
  String get driverScreenMoreOptions => 'Fler val: dölj typer';

  @override
  String get driverScreenMovedBody =>
      'Ditt konto används nu på en annan telefon. Logga in här igen om du vill flytta tillbaka. Telefonen går att byta en gång i månaden.';

  @override
  String get driverScreenMovedTitle => 'Inloggad på en annan telefon';

  @override
  String driverScreenMunicipalitiesChosen(int count) {
    String _temp0 = intl.Intl.pluralLogic(
      count,
      locale: localeName,
      other: '$count kommuner valda',
    );
    return '$_temp0';
  }

  @override
  String get driverScreenMyPosition => 'Min position';

  @override
  String get driverScreenNavFailed => 'Kunde inte öppna navigeringen.';

  @override
  String get driverScreenNearMe => 'Nära mig';

  @override
  String get driverScreenNearYou => 'Nära dig';

  @override
  String get driverScreenNearYou25 => 'Nära dig (25 km)';

  @override
  String get driverScreenNeedsInternet =>
      'Kräver internet. Försök igen när du har nät.';

  @override
  String get driverScreenNoAccess =>
      'Telefonen har ingen åtkomst. Logga in igen, eller be din chef att bjuda in dig.';

  @override
  String get driverScreenNoCountiesYet => 'Inga län än. Välj bil först.';

  @override
  String get driverScreenNoCounty => 'Inget län valt';

  @override
  String get driverScreenNoEventsDays => 'Inga event de här dagarna.';

  @override
  String driverScreenNoEventsWithin(int km) {
    return 'Inga event inom $km km. Välj ett längre avstånd.';
  }

  @override
  String get driverScreenNoFerries => 'Inga färjor på väg in just nu.';

  @override
  String driverScreenNoNewTips(String web) {
    return 'Nya tips visas inte just nu. $web Det är inte samma sak som \"inga störningar just nu\".';
  }

  @override
  String get driverScreenNoRoadAccidents =>
      'Inga trafikolyckor i ditt område just nu.';

  @override
  String get driverScreenNoTipsFilters => 'Inga tips med de här filtren.';

  @override
  String driverScreenNotUpdated(String time) {
    return 'Inte uppdaterat sedan $time';
  }

  @override
  String get driverScreenNothingSaved =>
      'Inget sparat än.\n\nTryck på ☆ på ett tips eller ett event. Tips sparas i sju dagar; event tills dagen efter.';

  @override
  String get driverScreenNow => 'Nu';

  @override
  String get driverScreenOnlyStrong => 'Bara starka';

  @override
  String get driverScreenOnlyStrongest => 'Bara starkast';

  @override
  String get driverScreenOpenSettings => 'Öppna inställningar';

  @override
  String driverScreenPausedBody(String notice) {
    return '$notice Det är inte samma sak som \"inga störningar just nu\".';
  }

  @override
  String get driverScreenPausedTitle => 'Medlemskapet är pausat';

  @override
  String get driverScreenPhonePaired => 'Telefon kopplad';

  @override
  String get driverScreenPositionFailed => 'Kunde inte hämta din position';

  @override
  String get driverScreenPositionFailedShort => 'Kunde inte hämta position';

  @override
  String get driverScreenPresetAll => 'Alla';

  @override
  String get driverScreenPresetStrong => 'Starka';

  @override
  String get driverScreenPresetStrongest => 'Starkast';

  @override
  String driverScreenRecentlyOver(int count) {
    return 'Nyss slut ($count)';
  }

  @override
  String get driverScreenRemovedSnack => 'Borttaget från sparade.';

  @override
  String get driverScreenResetFilter => 'Återställ filter';

  @override
  String get driverScreenRoadOnly =>
      'Bara trafikolyckor. Vägarbeten och avstängningar visas inte.';

  @override
  String get driverScreenSaveFailed => 'Kunde inte spara tipset';

  @override
  String get driverScreenSaved => 'Sparat';

  @override
  String get driverScreenSavedSnack =>
      'Sparat. Syns under ⭐ Sparat i sju dagar.';

  @override
  String get driverScreenSectionTips => 'Tips';

  @override
  String get driverScreenSeeSettings => 'Se inställningar';

  @override
  String get driverScreenSettings => 'Inställningar';

  @override
  String get driverScreenSettingsNewReply =>
      'Inställningar – nytt svar från supporten';

  @override
  String get driverScreenShow => 'Visa';

  @override
  String get driverScreenShowAll => 'Visa allt';

  @override
  String get driverScreenShowDistance => 'Visa avstånd';

  @override
  String get driverScreenShowFullList => 'Visa hela listan';

  @override
  String get driverScreenShowMap => 'Visa kartan';

  @override
  String get driverScreenSort => 'Sortera';

  @override
  String get driverScreenSortImportant => 'Viktigast';

  @override
  String get driverScreenSortNearest => 'Närmast';

  @override
  String get driverScreenSortNewest => 'Nyast';

  @override
  String get driverScreenStrength => 'Styrka';

  @override
  String driverScreenStrengthRange(int min, int max) {
    return 'Styrka $min–$max';
  }

  @override
  String get driverScreenTipGone =>
      'Tipset finns inte längre, eller så har bilen inte tillgång till det.';

  @override
  String get driverScreenTipsPausedTitle => 'Tipsen är pausade';

  @override
  String get driverScreenTrialEndedTitle => 'Provperioden är slut';

  @override
  String get driverScreenTrialNotStartedBody =>
      'Välj län under Inställningar. Förare bjuds in på webben. Provperioden startar när den första föraren loggar in.';

  @override
  String get driverScreenTrialNotStartedTitle => 'Välkommen! Ett steg kvar';

  @override
  String get driverScreenUnsaveFailed => 'Kunde inte ta bort tipset';

  @override
  String get driverScreenWholeCounty => 'Hela länet · välj kommuner';

  @override
  String get driverScreenWholeCountyShort => 'Hela länet';

  @override
  String get driverScreenWithin25 => 'Inom ca 25 km';

  @override
  String get driverScreenYellowShown => 'Gul = visas. Tryck för att dölja.';

  @override
  String get driverScreenZoomIn => 'Zooma in';

  @override
  String get driverScreenZoomOut => 'Zooma ut';

  @override
  String get driverTourCategoriesText =>
      'Välj vad du vill se: tåg och buss, väg, flyg, färja eller event. Siffran är antal tips. Sparat visar tipsen du har sparat.';

  @override
  String get driverTourCategoriesTitle => 'Kategorier';

  @override
  String get driverTourDrive => 'Kör dit';

  @override
  String get driverTourFilterText =>
      'Med Filter väljer du län, hur starka tips du vill se och vad som ska döljas. Välj ditt län här så får du tips därifrån.';

  @override
  String get driverTourFilterTitle => 'Filter och län';

  @override
  String get driverTourHowWasIt => 'Hur gick det?';

  @override
  String get driverTourListText =>
      'Här är tipsen nära dig. Det starkaste ligger överst. Dra listan uppåt för att se fler.';

  @override
  String get driverTourListTitle => 'Tipslistan';

  @override
  String get driverTourMapText =>
      'Varje nål är ett tips. Nålen har samma färg som tipset. Tryck på en nål för att öppna tipset. Överst förklarar frågetecknet symbolerna, och klockan i vänstra hörnet är Historik: tipsen från det senaste dygnet.';

  @override
  String get driverTourMapTitle => 'Kartan och nålarna';

  @override
  String get driverTourSave => 'Spara';

  @override
  String get driverTourSettingsDriver =>
      'Här slår du på notiser och väljer bilen du kör. Notiser säger till när ett starkt tips dyker upp nära dig. Genomgången finns kvar under Hjälp.';

  @override
  String get driverTourSettingsOwner =>
      'Här väljer du län och slår på notiser. Förare bjuds in på webben. Här väljer du också vilken plats du kör med. Genomgången finns kvar under Hjälp.';

  @override
  String get driverTourSettingsTitle => 'Inställningar';

  @override
  String get driverTourStrengthText =>
      'Varje tips har en färg och ett ord. Längst ner i listan finns \"Övrigt\": meddelanden från trafikbolag. Det är information, inte tips.';

  @override
  String get driverTourStrengthTitle => 'Färgen visar styrkan';

  @override
  String get driverTourTipText =>
      'Då öppnas ett blad med mer om tipset. Där kan du köra dit, spara tipset och svara hur det gick. Svaren gör tipsen bättre.';

  @override
  String get driverTourTipTitle => 'Tryck på ett tips';

  @override
  String get eventsScreenAllCounties => 'Alla län';

  @override
  String get eventsScreenAllKinds => 'Alla sorter';

  @override
  String eventsScreenCount(int count) {
    String _temp0 = intl.Intl.pluralLogic(
      count,
      locale: localeName,
      other: '$count evenemang',
    );
    return '$_temp0';
  }

  @override
  String eventsScreenError(String error) {
    return 'Kunde inte hämta evenemangen: $error';
  }

  @override
  String get eventsScreenFollowing =>
      'Du följer eventet. Det finns under ⭐ Sparat på kartan.';

  @override
  String eventsScreenLoading(String period) {
    return 'Hämtar $period…';
  }

  @override
  String get eventsScreenMonth => '30 dagar';

  @override
  String eventsScreenNone(String period) {
    return 'Inga evenemang $period i ditt område.';
  }

  @override
  String get eventsScreenNoneHint =>
      'Dagarna ovan har evenemang — tryck på en av dem, eller välj en längre period.';

  @override
  String get eventsScreenNoneThin =>
      'Utbudet är tunt utanför storstäderna. Prova ett annat län.';

  @override
  String get eventsScreenOtherKind => 'Övrigt';

  @override
  String get eventsScreenPickDay => 'Välj dag';

  @override
  String get eventsScreenPickPeriod => 'Välj period';

  @override
  String get eventsScreenQuarter => '3 månader';

  @override
  String get eventsScreenSortLargest => 'Störst';

  @override
  String get eventsScreenSortNearest => 'Närmast';

  @override
  String get eventsScreenSortTime => 'Tid';

  @override
  String eventsScreenSummary(String count, String period) {
    return '$count · $period';
  }

  @override
  String eventsScreenSummaryFiltered(int shown, int total, String period) {
    return '$shown av $total evenemang · $period';
  }

  @override
  String get eventsScreenTitle => 'Evenemang';

  @override
  String get eventsScreenToday => 'I dag';

  @override
  String get eventsScreenTodayPrefix => 'I dag · ';

  @override
  String get eventsScreenTomorrow => 'I morgon';

  @override
  String get eventsScreenTomorrowPrefix => 'I morgon · ';

  @override
  String get eventsScreenUnfollowed => 'Du följer det inte längre.';

  @override
  String get eventsScreenWeek => '7 dagar';

  @override
  String get eventsScreenWeekend => 'Helgen';

  @override
  String get eventsScreenWholeArea => 'Hela området';

  @override
  String get ferryEventApproaching => 'På väg in';

  @override
  String get ferryEventAtQuay => 'Vid kaj';

  @override
  String ferryEventAtQuaySince(String clock) {
    return 'Vid kaj sedan $clock';
  }

  @override
  String ferryEventAtTime(String time) {
    return 'Kl $time';
  }

  @override
  String get ferryEventByTimetable => 'Enligt tidtabell';

  @override
  String get ferryEventConfirmed => 'Bekräftad';

  @override
  String get ferryEventConfirmedApproaching =>
      'Bekräftad – fartyget är på väg in';

  @override
  String get ferryEventConfirmedBerthed =>
      'Bekräftad – fartyget ligger vid kaj';

  @override
  String ferryEventDistance(String distance, String time) {
    return '$distance · ca $time med bil';
  }

  @override
  String get ferryEventDockingNow => 'Lägger till nu';

  @override
  String ferryEventDocksAt(String clock, String relative) {
    return 'Lägger till $clock · $relative';
  }

  @override
  String ferryEventEarly(String time) {
    return '$time tidig';
  }

  @override
  String get ferryEventEndEstimated =>
      'Sluttiden är uppskattad, inte angiven av arrangören.';

  @override
  String ferryEventEndsAbout(String time) {
    return 'Slutar ca $time';
  }

  @override
  String get ferryEventFerry => 'Färja';

  @override
  String get ferryEventFollow => 'Följ';

  @override
  String get ferryEventFollowing => 'Följer';

  @override
  String ferryEventFrom(String place) {
    return 'Från $place';
  }

  @override
  String get ferryEventInternational => 'Utrikes';

  @override
  String ferryEventLate(String time) {
    return '$time sen';
  }

  @override
  String get ferryEventOnTime => 'I tid';

  @override
  String get ferryEventOngoing => 'Pågår nu';

  @override
  String ferryEventOriginDeparted(String from, String clock) {
    return '$from, avgick $clock';
  }

  @override
  String ferryEventOriginDeparts(String from, String clock) {
    return '$from, avgår $clock';
  }

  @override
  String ferryEventPeopleLeave(String time) {
    return 'Folk går till $time';
  }

  @override
  String ferryEventPickupNow(String clock) {
    return 'Folk kommer ut nu, till $clock';
  }

  @override
  String ferryEventPickupRange(String range) {
    return 'Folk kommer ut $range';
  }

  @override
  String ferryEventPickupValueNow(String clock) {
    return 'nu, till $clock';
  }

  @override
  String ferryEventReachAfter(String clock) {
    return 'Framme ca $clock – efter att de flesta gått';
  }

  @override
  String ferryEventReachBefore(String clock) {
    return 'Framme ca $clock – före folk kommer ut';
  }

  @override
  String ferryEventReachDuring(String clock) {
    return 'Framme ca $clock – medan folk kommer ut';
  }

  @override
  String ferryEventReachNoWindow(String clock) {
    return 'Framme ca $clock';
  }

  @override
  String get ferryEventRowArrival => 'Ankomst';

  @override
  String get ferryEventRowAtQuay => 'Vid kajen';

  @override
  String get ferryEventRowCertainty => 'Hur säkert';

  @override
  String get ferryEventRowComingFrom => 'Kommer från';

  @override
  String get ferryEventRowDelay => 'Försening';

  @override
  String get ferryEventRowDistance => 'Avstånd';

  @override
  String get ferryEventRowEndsAbout => 'Slutar ca';

  @override
  String get ferryEventRowKind => 'Sort';

  @override
  String get ferryEventRowOperator => 'Rederi';

  @override
  String get ferryEventRowPeopleCome => 'Folk kommer ut';

  @override
  String get ferryEventRowPeopleLeaving => 'Folk på väg ut';

  @override
  String get ferryEventRowQuay => 'Kaj';

  @override
  String get ferryEventRowReach => 'Hinner du';

  @override
  String get ferryEventRowRoute => 'Linje';

  @override
  String get ferryEventRowSameQuay => 'Samma kaj ±30 min';

  @override
  String get ferryEventRowService => 'Trafik';

  @override
  String get ferryEventRowSize => 'Storlek';

  @override
  String get ferryEventRowStatus => 'Status';

  @override
  String get ferryEventRowTimetable => 'Tidtabell';

  @override
  String ferryEventSameMany(int count) {
    String _temp0 = intl.Intl.pluralLogic(
      count,
      locale: localeName,
      other: '$count färjor till anländer',
    );
    return '$_temp0';
  }

  @override
  String ferryEventSameManyFirst(int count, String at) {
    String _temp0 = intl.Intl.pluralLogic(
      count,
      locale: localeName,
      other: '$count färjor till anländer, första $at',
    );
    return '$_temp0';
  }

  @override
  String get ferryEventSameOne => '1 färja till anländer';

  @override
  String ferryEventSameOneAt(String at) {
    return '1 färja till anländer $at';
  }

  @override
  String get ferryEventSectionContext => 'Sammanhang';

  @override
  String get ferryEventSectionWhen => 'När';

  @override
  String get ferryEventSectionWhere => 'Var';

  @override
  String get ferryEventSectionWho => 'Vilka kliver av';

  @override
  String ferryEventShouldHaveDocked(String clock) {
    return 'Skulle lägga till $clock enligt tidtabell';
  }

  @override
  String get ferryEventSizeLarge => 'Stor färja';

  @override
  String get ferryEventSizeMedium => 'Medelstor färja';

  @override
  String get ferryEventSizeSmall => 'Mindre färja';

  @override
  String get ferryEventTimeNotSet => 'Tid ej satt';

  @override
  String get ferryEventToday => 'i dag';

  @override
  String get ferryEventTomorrow => 'i morgon';

  @override
  String get ferryEventUnknown => 'okänt';

  @override
  String ferryEventVenueCapacity(String capacity) {
    return 'Arena för $capacity';
  }

  @override
  String ferryEventVenueCapacityNote(String capacity) {
    return 'arena för $capacity (kapacitet, inte publik)';
  }

  @override
  String get followUpCardClose => 'Stäng';

  @override
  String followUpCardDrove(String place, String time) {
    return 'Du körde mot $place $time';
  }

  @override
  String get forceUpgradeBody =>
      'Den här versionen fungerar inte längre. Uppdatera för att fortsätta.';

  @override
  String get forceUpgradeClose => 'Stäng';

  @override
  String get forceUpgradeNudge => 'Ny version finns. Uppdatera när du kan.';

  @override
  String get forceUpgradeTitle => 'Uppdatera appen';

  @override
  String get forceUpgradeUpdate => 'Uppdatera';

  @override
  String forceUpgradeVersions(String installed, String required) {
    return 'Din version: $installed  ·  Krävs: $required';
  }

  @override
  String get guidedTourDone => 'Klar';

  @override
  String get guidedTourNext => 'Nästa';

  @override
  String get guidedTourSkip => 'Hoppa över';

  @override
  String guidedTourStep(int position, int total) {
    return 'Steg $position av $total';
  }

  @override
  String get historyScreenAnd => ' och ';

  @override
  String get historyScreenEarlier => 'Började tidigare';

  @override
  String get historyScreenEnded => 'Slut';

  @override
  String historyScreenHidden(int count) {
    return '$count tips visas inte.';
  }

  @override
  String historyScreenHiddenIn(int count, String categories) {
    return '$count tips i $categories visas inte.';
  }

  @override
  String historyScreenHours(int hours) {
    return '$hours tim';
  }

  @override
  String get historyScreenLoadError =>
      'Kunde inte hämta historiken. Försök igen.';

  @override
  String get historyScreenNeedsArea =>
      'Välj ditt körområde för att se historiken.';

  @override
  String get historyScreenNoAccess =>
      'Historiken visas när telefonen har åtkomst till tips.';

  @override
  String historyScreenNone(int hours) {
    return 'Inga tips de senaste $hours timmarna.';
  }

  @override
  String get historyScreenOngoing => 'Pågår';

  @override
  String get historyScreenRetry => 'Försök igen';

  @override
  String historyScreenShowingLatest(int count) {
    return 'Visar de $count senaste.';
  }

  @override
  String historyScreenSummary(int count, int hours, int active) {
    return '$count tips de senaste $hours timmarna · $active pågår';
  }

  @override
  String get historyScreenTitle => 'Historik';

  @override
  String get historyScreenUnavailable =>
      'Historiken finns inte i den här versionen.';

  @override
  String get languageButtonLabel => 'Byt språk';

  @override
  String languageCurrentAuto(String language) {
    return '$language (telefonens språk)';
  }

  @override
  String get languageFollowPhone => 'Telefonens språk';

  @override
  String languageFollowPhoneDetail(String language) {
    return 'Nu: $language';
  }

  @override
  String get languageSectionDescription =>
      'Appen följer telefonens språk om den finns på det.';

  @override
  String get languageTitle => 'Språk';

  @override
  String get loginScreenBack => 'Tillbaka';

  @override
  String get loginScreenCreateAccount => 'Skapa konto gratis';

  @override
  String get loginScreenDeviceSwapLimit =>
      'Du har bytt telefon en gång den här månaden. Kontakta support så hjälper vi dig byta igen.';

  @override
  String get loginScreenEmail => 'E-post';

  @override
  String get loginScreenEmailNotConfirmed =>
      'Bekräfta din e-post först. Tryck på länken i mejlet.';

  @override
  String get loginScreenEnterCredentials =>
      'Skriv din e-post och ditt lösenord.';

  @override
  String get loginScreenFailed => 'Det gick inte att logga in. Försök igen.';

  @override
  String get loginScreenForgotPassword => 'Glömt lösenord?';

  @override
  String get loginScreenHidePassword => 'Dölj lösenord';

  @override
  String get loginScreenIntro =>
      'För förare, ägare och kontor. Ny förare? Välj först ett lösenord med länken i inbjudan.';

  @override
  String get loginScreenNoAccount => 'Inget konto?';

  @override
  String get loginScreenNoInvite =>
      'Kontot är inte kopplat till något taxibolag. Be din chef bjuda in dig, eller tryck på Skapa konto gratis nedan.';

  @override
  String get loginScreenPassword => 'Lösenord';

  @override
  String get loginScreenRateLimit => 'Vänta en minut och försök igen.';

  @override
  String loginScreenRecovered(String email) {
    return 'Klart! Logga in med $email.';
  }

  @override
  String get loginScreenShowPassword => 'Visa lösenord';

  @override
  String get loginScreenTagline =>
      'Se var folk behöver taxi,\ninnan kön växer.';

  @override
  String get loginScreenTitle => 'Logga in';

  @override
  String get loginScreenWithBankId => 'Logga in med BankID';

  @override
  String get loginScreenWrongCredentials => 'Fel e-post eller lösenord.';

  @override
  String get membershipCopyAccessNotActive => 'Åtkomsten är inte aktiv.';

  @override
  String get membershipCopyInvoicesOnWeb =>
      'Fakturor och medlemskap hanteras av företagets administratör på webben.';

  @override
  String get membershipCopyNotActive => 'Medlemskapet är inte aktivt just nu.';

  @override
  String get membershipCopyNotInMembership => 'Ingår inte i ditt medlemskap.';

  @override
  String get membershipCopyNotInTrial => 'Ingår inte i provet.';

  @override
  String get membershipCopyOnWeb =>
      'Ditt företags administratör hanterar medlemskapet på webben.';

  @override
  String get membershipCopyPaused => 'Medlemskapet är pausat.';

  @override
  String get membershipCopyPortalSubtitle =>
      'Öppnar kundportalen på webben: bilar, fakturor och medlemmar.';

  @override
  String get membershipCopyPortalTitle => 'Hantera företagskonto';

  @override
  String get membershipCopyPromiseNoBinding => 'Ingen bindning';

  @override
  String get membershipCopyPromiseNoCard => 'Inget kort';

  @override
  String get membershipCopyPromiseNoCompany => 'Inget företag behövs';

  @override
  String get membershipCopyTrialEnded => 'Provperioden är slut.';

  @override
  String get membershipCountyContinue => 'Fortsätt';

  @override
  String get membershipCountyLoadFailed =>
      'Kunde inte hämta länen. Dra ner för att försöka igen.';

  @override
  String get membershipCountyRetry => 'Försök igen';

  @override
  String get membershipCountySubtitle =>
      'Välj länet där du kör mest. Du kan byta senare.';

  @override
  String get membershipCountyTitle => 'Var vill du köra?';

  @override
  String get netStatusGenericError => 'Något gick fel. Försök igen.';

  @override
  String get netStatusOffline => 'Ingen internetanslutning';

  @override
  String get netStatusTimeout => 'Dålig uppkoppling. Försök igen.';

  @override
  String get netStatusUnreachable => 'Servern svarar inte just nu';

  @override
  String get notificationLogSheetArchived => '· arkiverad';

  @override
  String get notificationLogSheetEmptyBody =>
      'Notiser skickas bara för störningar som är värda att avbryta för. Är det lugnt i dina län hör du inget — och det är meningen.';

  @override
  String get notificationLogSheetEmptyTitle => 'Inga notiser än';

  @override
  String notificationLogSheetHoursAgo(int hours) {
    return 'För $hours tim sedan';
  }

  @override
  String get notificationLogSheetIntro =>
      'Notiser som skickats till den här telefonen. Vill du spara ett tips? Gör det med stjärnan i tipslistan — då ligger det under Sparat i sju dagar.';

  @override
  String notificationLogSheetMinAgo(int minutes) {
    return 'För $minutes min sedan';
  }

  @override
  String get notificationLogSheetNeedsBackend => 'Notishistorik kräver backend';

  @override
  String get notificationLogSheetNoPhone => 'Ingen parad telefon';

  @override
  String get notificationLogSheetNoPhoneBody =>
      'Notiser skickas till en parad enhet. Den här inloggningen har ingen.';

  @override
  String get notificationLogSheetNow => 'Just nu';

  @override
  String get notificationLogSheetTitle => 'Mina notiser';

  @override
  String notifyPrefsAreaLine(String counties) {
    return 'Körområde: $counties';
  }

  @override
  String get notifyPrefsByArea => 'Enligt körområdet';

  @override
  String get notifyPrefsHowImportant => 'Hur viktiga?';

  @override
  String get notifyPrefsLevelAll => 'Alla';

  @override
  String get notifyPrefsLevelMedium => 'Medel +';

  @override
  String get notifyPrefsLevelStrong => 'Starka';

  @override
  String get notifyPrefsMoreOptions => 'Fler val';

  @override
  String get notifyPrefsNeedsLocation =>
      'I tjänst behöver plats när appen används';

  @override
  String get notifyPrefsNoActiveSeat =>
      'Ingen aktiv plats på den här enheten — inställningarna kan inte sparas.';

  @override
  String get notifyPrefsOnAgain => 'Notiserna är på igen.';

  @override
  String get notifyPrefsOnDuty => 'I tjänst';

  @override
  String get notifyPrefsPause => 'Paus';

  @override
  String get notifyPrefsPause1h => '1 tim';

  @override
  String get notifyPrefsPause4h => '4 tim';

  @override
  String get notifyPrefsPauseTonight => 'I natt';

  @override
  String notifyPrefsPausedUntilSnack(String time) {
    return 'Pausat till $time.';
  }

  @override
  String notifyPrefsPausedUntilTitle(String time) {
    return 'Pausat till $time';
  }

  @override
  String get notifyPrefsResume => 'Starta igen';

  @override
  String get notifyPrefsSaved => 'Sparat';

  @override
  String get notifyPrefsSendNotifications => 'Skicka notiser';

  @override
  String get notifyPrefsTitle => 'Notiser';

  @override
  String notifyPrefsTomorrowAt(String time) {
    return 'i morgon $time';
  }

  @override
  String get notifyPrefsWhichNotifications => 'Vilka notiser?';

  @override
  String get notifyPrefsWithinKm => 'Inom 30 km av dig';

  @override
  String get notifyRulesApiInvalidResponse => 'Ogiltigt svar från servern';

  @override
  String notifyRulesApiServerResponded(int status) {
    return 'Servern svarade $status';
  }

  @override
  String offlineBannerOffline(String at) {
    return 'Offline – visar senaste tips från $at';
  }

  @override
  String get offlineBannerRetry => 'Försök igen';

  @override
  String offlineBannerTimeout(String at) {
    return 'Dålig uppkoppling – visar tips från $at';
  }

  @override
  String offlineBannerUnreachable(String at) {
    return 'Servern svarar inte – visar tips från $at';
  }

  @override
  String get onboardingScreenClose => 'Stäng';

  @override
  String get onboardingScreenColorsBody =>
      'Det är tips, inte beställningar. Du avgör själv om det är värt att åka.';

  @override
  String get onboardingScreenColorsTitle => 'Färgen visar hur starkt tipset är';

  @override
  String get onboardingScreenDone => 'Klar';

  @override
  String get onboardingScreenFeedbackBody =>
      'Tryck på ett tips och välj Fick körning eller Ingen kund. Då blir tipsen bättre för alla.';

  @override
  String get onboardingScreenFeedbackTitle => 'Säg hur det gick';

  @override
  String get onboardingScreenLevelMedium => 'Medel';

  @override
  String get onboardingScreenLevelMediumText => 'Kan bli körningar. Håll koll.';

  @override
  String get onboardingScreenLevelStrong => 'Stark';

  @override
  String get onboardingScreenLevelStrongText => 'Många kan behöva taxi.';

  @override
  String get onboardingScreenLevelWeak => 'Svag';

  @override
  String get onboardingScreenLevelWeakText =>
      'Bra att veta, sällan värt att åka.';

  @override
  String get onboardingScreenNext => 'Nästa';

  @override
  String get onboardingScreenNotifBody =>
      'Slå på notiser under Inställningar. Då säger vi till när ett starkt tips dyker upp nära dig.';

  @override
  String get onboardingScreenNotifTitle => 'Notiser';

  @override
  String onboardingScreenPageOf(int page, int total) {
    return 'Sida $page av $total';
  }

  @override
  String get onboardingScreenSkip => 'Hoppa över';

  @override
  String get onboardingScreenStartBody =>
      'Skapa ett konto gratis, eller logga in om du redan har ett. Sedan visar vi dig runt i appen.';

  @override
  String get onboardingScreenStartTitle => 'Kom igång';

  @override
  String get onboardingScreenTrafficBody =>
      'Inställda tåg, sena flyg, färjor och event som slutar. Vi visar var folk kan behöva taxi. Det är tips, inte beställningar.';

  @override
  String get onboardingScreenTrafficTitle => 'Tips från trafiken';

  @override
  String get settingsScreenAboutTips => 'Om tipsen';

  @override
  String get settingsScreenAccountClosed => 'Kontot är avslutat.';

  @override
  String get settingsScreenAccountDescription =>
      'Logga ut om du slutar köra eller byter telefon.';

  @override
  String get settingsScreenAccountTitle => 'Konto';

  @override
  String get settingsScreenCancel => 'Avbryt';

  @override
  String get settingsScreenCloseAccountBody =>
      'Medlemskapet förnyas inte. Pågår ett prov avslutas det. Ni kan använda appen perioden ut.';

  @override
  String get settingsScreenCloseAccountConfirm => 'Avsluta';

  @override
  String get settingsScreenCloseAccountTitle => 'Avsluta företagskontot?';

  @override
  String get settingsScreenCloseCompanyAccount => 'Avsluta företagskontot';

  @override
  String get settingsScreenCompanyDescription =>
      'Hantera företagskontot i kundportalen på webben.';

  @override
  String get settingsScreenCompanyTitle => 'Företaget';

  @override
  String get settingsScreenCountiesMany =>
      'Tips och notiser i dina län. Tryck för att välja vilka.';

  @override
  String get settingsScreenCountiesOne => 'Tips och notiser i det här länet.';

  @override
  String get settingsScreenDelete => 'Radera';

  @override
  String get settingsScreenDeleteBodyDriver =>
      'Ditt förarkonto tas bort och enheten kopplas från din plats. Din chef kan bjuda in dig igen. Det går inte att ångra.';

  @override
  String get settingsScreenDeleteBodyOffice =>
      'Ditt konto och din inloggning tas bort för gott. Enheter du kört med kopplas från medlemskapet.\n\nÄr du ensam ägare avslutas företaget direkt: medlemskapet och ett pågående prov upphör, förarna slutar få tips och företaget arkiveras. Det går inte att ångra.';

  @override
  String get settingsScreenDeleteFailedTitle => 'Kontot raderades inte';

  @override
  String get settingsScreenDeleteMyAccount => 'Radera mitt konto';

  @override
  String get settingsScreenDeleteTitle => 'Radera ditt konto?';

  @override
  String get settingsScreenDeleted => 'Ditt konto är raderat.';

  @override
  String get settingsScreenHelpChat => 'Chatta med oss';

  @override
  String get settingsScreenHelpDescription =>
      'Se hur appen fungerar, eller skriv till oss.';

  @override
  String get settingsScreenHelpHowDriver => 'Fyra korta sidor';

  @override
  String get settingsScreenHelpHowItWorks => 'Så fungerar Taxi Tips';

  @override
  String get settingsScreenHelpHowOffice => 'Provet, medlemskap och förare';

  @override
  String get settingsScreenHelpTitle => 'Hjälp';

  @override
  String get settingsScreenHelpTour => 'Visa genomgången igen';

  @override
  String get settingsScreenHelpTourSub => 'Visar var du trycker på startsidan';

  @override
  String settingsScreenHelpUnread(int count) {
    String _temp0 = intl.Intl.pluralLogic(
      count,
      locale: localeName,
      other: '$count nya svar',
      one: 'Ett nytt svar',
    );
    return '$_temp0';
  }

  @override
  String get settingsScreenLoginForSettings =>
      'Logga in för att se inställningarna.';

  @override
  String get settingsScreenLogout => 'Logga ut';

  @override
  String get settingsScreenMembershipDescription =>
      'Platsen du kör med och länen du får tips från.';

  @override
  String settingsScreenMembershipDescriptionCompany(String company) {
    return 'Platsen du kör med och länen du får tips från. Företag: $company.';
  }

  @override
  String get settingsScreenMembershipTitle => 'Medlemskap';

  @override
  String get settingsScreenNotifyAllCounties => 'Alla dina län';

  @override
  String get settingsScreenNotifyDescription =>
      'Välj när telefonen ska säga till om ett starkt tips.';

  @override
  String settingsScreenNotifyFilter(String counties) {
    return 'Filter: $counties';
  }

  @override
  String get settingsScreenNotifyTitle => 'Notiser';

  @override
  String get settingsScreenOk => 'OK';

  @override
  String get settingsScreenPrivacy => 'Datapolicy';

  @override
  String get settingsScreenSignedInAs => 'Inloggad som';

  @override
  String get settingsScreenTerms => 'Villkor';

  @override
  String get settingsScreenTitle => 'Inställningar';

  @override
  String get settingsScreenYourCounties => 'Dina län';

  @override
  String severityLabelsCancelledAt(String clock) {
    return 'Inställd $clock';
  }

  @override
  String severityLabelsClockChange(String from, String to) {
    return '$from → $to';
  }

  @override
  String get severityLabelsCompensationBase => 'Resenären kan få taxin betald';

  @override
  String get severityLabelsCompensationMaybe => 'Taxi kan ersättas';

  @override
  String severityLabelsCompensationSentenceUpTo(String amount, String per) {
    String _temp0 = intl.Intl.selectLogic(per, {
      'person': ' per resenär',
      'trip': ' per resa',
      'other': '',
    });
    return 'Resenären kan få taxin betald upp till $amount kr$_temp0';
  }

  @override
  String severityLabelsCompensationUpTo(int amount, String per) {
    String _temp0 = intl.Intl.selectLogic(per, {
      'person': ' per resenär',
      'trip': ' per resa',
      'other': '',
    });
    return 'Taxi ersätts · upp till $amount kr$_temp0';
  }

  @override
  String get severityLabelsConfidenceHigh => 'Hög — tydligt i källdatan';

  @override
  String get severityLabelsConfidenceLow =>
      'Låg — osäker tolkning av källdatan';

  @override
  String get severityLabelsConfidenceMedium => 'Medel';

  @override
  String get severityLabelsDelayed => 'Försenad';

  @override
  String severityLabelsDelayedBy(String delay) {
    return 'Försenad $delay';
  }

  @override
  String get severityLabelsDeparted => 'har gått';

  @override
  String get severityLabelsDepartsNow => 'avgår nu';

  @override
  String severityLabelsHours(int hours) {
    return '$hours tim';
  }

  @override
  String severityLabelsHoursMinutes(int hours, int minutes) {
    return '$hours tim $minutes min';
  }

  @override
  String severityLabelsIn(String time) {
    return 'om $time';
  }

  @override
  String severityLabelsMinutes(int minutes) {
    return '$minutes min';
  }

  @override
  String get severityLabelsModeBoat => 'Båt';

  @override
  String get severityLabelsModeBus => 'Buss';

  @override
  String get severityLabelsModeEvents => 'Evenemang';

  @override
  String get severityLabelsModeFerries => 'Färjor';

  @override
  String get severityLabelsModeFlight => 'Flyg';

  @override
  String get severityLabelsModeMetro => 'Tunnelbana';

  @override
  String get severityLabelsModeRoad => 'Väg';

  @override
  String get severityLabelsModeTrain => 'Tåg';

  @override
  String get severityLabelsModeTram => 'Spårvagn';

  @override
  String severityLabelsMonthShort(String m) {
    String _temp0 = intl.Intl.selectLogic(m, {
      'm1': 'jan',
      'm2': 'feb',
      'm3': 'mar',
      'm4': 'apr',
      'm5': 'maj',
      'm6': 'jun',
      'm7': 'jul',
      'm8': 'aug',
      'm9': 'sep',
      'm10': 'okt',
      'm11': 'nov',
      'm12': 'dec',
      'other': '',
    });
    return '$_temp0';
  }

  @override
  String get severityLabelsShortArrivalWave => 'Ankomstvåg';

  @override
  String get severityLabelsShortIgnore => 'Övrigt';

  @override
  String get severityLabelsShortLastArrival => 'Sista ankomsten';

  @override
  String get severityLabelsShortLineDelayed => 'Försening, linjen kör';

  @override
  String get severityLabelsShortLinePaused => 'Hela linjen stoppad';

  @override
  String get severityLabelsShortRoadAccident => 'Olycka/avstängning';

  @override
  String get severityLabelsShortRoadWork => 'Vägarbete';

  @override
  String get severityLabelsShortRoadWorkQueue => 'Vägarbete/kö';

  @override
  String get severityLabelsShortUnclassified => 'Osäker bedömning';

  @override
  String get severityLabelsShortVehicleCancelled => 'Enstaka avgång inställd';

  @override
  String get severityLabelsShortVehicleDelayed => 'Enstaka avgång försenad';

  @override
  String get severityLabelsTierArrivalWave => 'Många flyg landar samtidigt';

  @override
  String get severityLabelsTierArrivalWaveFerry =>
      'Många färjor kommer in samtidigt';

  @override
  String get severityLabelsTierIgnore => 'Övrigt – trafikbolagets meddelande';

  @override
  String get severityLabelsTierLastArrival =>
      'Sista planet — inget mer landar på flera timmar';

  @override
  String get severityLabelsTierLastArrivalFerry =>
      'Sista färjan — inget mer anländer på flera timmar';

  @override
  String get severityLabelsTierLineDelayed => 'Försening på linjen';

  @override
  String get severityLabelsTierLinePaused => 'Hela linjen är stoppad';

  @override
  String get severityLabelsTierRoadAccident => 'Olycka eller avstängd väg';

  @override
  String get severityLabelsTierRoadWork => 'Mindre vägarbete';

  @override
  String get severityLabelsTierRoadWorkQueue => 'Vägarbete eller köbildning';

  @override
  String get severityLabelsTierUnclassified =>
      'Störning (osäker klassificering)';

  @override
  String get severityLabelsTierVehicleCancelled => 'En avgång inställd';

  @override
  String get severityLabelsTierVehicleDelayed => 'En avgång försenad';

  @override
  String get severityLabelsTipFallback => 'Tips';

  @override
  String severityLabelsTitleWithMode(String mode, String title) {
    return '$mode: $title';
  }

  @override
  String severityLabelsTowards(String destination) {
    return 'mot $destination';
  }

  @override
  String get severityLabelsWaitLast => 'Sista avgången härifrån';

  @override
  String severityLabelsWaitThere(String at, String gap) {
    return 'Nästa dit$at, $gap senare';
  }

  @override
  String severityLabelsWaitThereFirst(String at, String gap) {
    return 'Nästa dit först$at, $gap senare';
  }

  @override
  String severityLabelsWaitTrip(String at, String gap) {
    return 'Nästa resa$at, $gap senare';
  }

  @override
  String severityLabelsWaitTripFirst(String at, String gap) {
    return 'Nästa resa först$at, $gap senare';
  }

  @override
  String get signalCardDrive => 'Kör dit';

  @override
  String get signalCardNoteBody =>
      'Vi läser av trafiken och visar var folk kan behöva taxi. Du avgör själv om det är värt att åka.';

  @override
  String get signalCardNoteLine =>
      'Tips från trafikläget, ingen garanti för körning';

  @override
  String signalCardNoteMore(String title) {
    return '$title. Visa mer';
  }

  @override
  String get signalCardNoteOk => 'Uppfattat';

  @override
  String get signalCardNoteTitle => 'Tips, inte beställningar';

  @override
  String get signalCardOver => 'Slut';

  @override
  String get signalCardSave => 'Spara tipset';

  @override
  String get signalCardTaxiPays => 'Taxi betalas';

  @override
  String get signalCardUnsave => 'Ta bort sparat';

  @override
  String signalKindsAgoDays(int days) {
    return '$days d';
  }

  @override
  String get signalKindsAgoNow => 'Nu';

  @override
  String get signalKindsCategoryEvent => 'Event';

  @override
  String get signalKindsCategoryFerry => 'Färja';

  @override
  String get signalKindsCategoryFlight => 'Flyg';

  @override
  String get signalKindsCategoryRoad => 'Väg';

  @override
  String get signalKindsCategoryTransit => 'Tåg & buss';

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
      'Match, konsert eller annat. Publiken går hem samtidigt.';

  @override
  String get signalKindsExplainFerry =>
      'Färja på väg in. Folk kliver av i hamnen.';

  @override
  String get signalKindsExplainFlight =>
      'Många flyg landar, eller sista flyget. Folk behöver taxi från flygplatsen.';

  @override
  String get signalKindsExplainRoad =>
      'Trafikolycka. Räkna med kö, eller kör en annan väg.';

  @override
  String get signalKindsExplainTransit =>
      'Tåg, buss eller tunnelbana står still eller är sen. Folk behöver taxi.';

  @override
  String signalKindsLongDayRelative(String relative, String weekday) {
    return '$relative, $weekday';
  }

  @override
  String get signalKindsMeaningHigh => 'Troligt att folk behöver taxi här.';

  @override
  String get signalKindsMeaningLow => 'Troligen få som behöver taxi här.';

  @override
  String get signalKindsMeaningMedium => 'Kan vara värt att följa. Håll koll.';

  @override
  String signalKindsMonthLong(String m) {
    String _temp0 = intl.Intl.selectLogic(m, {
      'm1': 'januari',
      'm2': 'februari',
      'm3': 'mars',
      'm4': 'april',
      'm5': 'maj',
      'm6': 'juni',
      'm7': 'juli',
      'm8': 'augusti',
      'm9': 'september',
      'm10': 'oktober',
      'm11': 'november',
      'm12': 'december',
      'other': '',
    });
    return '$_temp0';
  }

  @override
  String get signalKindsRoadClosed => 'Vägen avstängd';

  @override
  String get signalKindsRoadHazard => 'Hinder på vägen';

  @override
  String get signalKindsRoadMajor => 'Stor störning';

  @override
  String get signalKindsToday => 'I dag';

  @override
  String get signalKindsTomorrow => 'I morgon';

  @override
  String signalKindsWeekdayLong(String d) {
    String _temp0 = intl.Intl.selectLogic(d, {
      'd1': 'måndag',
      'd2': 'tisdag',
      'd3': 'onsdag',
      'd4': 'torsdag',
      'd5': 'fredag',
      'd6': 'lördag',
      'd7': 'söndag',
      'other': '',
    });
    return '$_temp0';
  }

  @override
  String signalKindsWeekdayShort(String d) {
    String _temp0 = intl.Intl.selectLogic(d, {
      'd1': 'mån',
      'd2': 'tis',
      'd3': 'ons',
      'd4': 'tor',
      'd5': 'fre',
      'd6': 'lör',
      'd7': 'sön',
      'other': '',
    });
    return '$_temp0';
  }

  @override
  String get signalKindsWordAccident => 'Olycka';

  @override
  String get signalKindsWordBig => 'Stort';

  @override
  String get signalKindsWordMedium => 'Medel';

  @override
  String get signalKindsWordMiddle => 'Mellan';

  @override
  String get signalKindsWordQueue => 'Kö';

  @override
  String get signalKindsWordSmall => 'Litet';

  @override
  String get signalKindsWordStrong => 'Stark';

  @override
  String get signalKindsWordWeak => 'Svag';

  @override
  String get signalKindsWordWork => 'Arbete';

  @override
  String get signalKindsYesterday => 'I går';

  @override
  String signalMapCluster(int count) {
    return '$count saker här';
  }

  @override
  String signalMapFerry(String name) {
    return 'Färja $name';
  }

  @override
  String get signupScreenBack => 'Tillbaka';

  @override
  String get signupScreenCompanyHelp => 'Organisationsnummer behövs inte nu.';

  @override
  String get signupScreenCompanyHint => 'Till exempel Annas Taxi';

  @override
  String get signupScreenCompanyLabel => 'Företagets namn';

  @override
  String get signupScreenCompanyQuestion => 'Vad heter företaget?';

  @override
  String get signupScreenCompanyText => 'Med egna bilar eller förare.';

  @override
  String get signupScreenCompanyTitle => 'Jag äger ett taxibolag';

  @override
  String get signupScreenContinueBankId => 'Fortsätt med BankID';

  @override
  String get signupScreenCreateAccount => 'Skapa kontot';

  @override
  String get signupScreenDateInvalid =>
      'Personnumret har ett datum som inte finns. Kontrollera numret.';

  @override
  String get signupScreenEmailHelp => 'Du loggar in med den.';

  @override
  String get signupScreenEmailLabel => 'E-post';

  @override
  String get signupScreenEmailQuestion => 'Din e-post';

  @override
  String get signupScreenHaveAccount => 'Har du redan ett konto? Logga in';

  @override
  String get signupScreenKindQuestion => 'Är du förare eller ägare?';

  @override
  String signupScreenKindQuestionNamed(String name) {
    return 'Hej $name! Är du förare eller ägare?';
  }

  @override
  String get signupScreenLoginInstead => 'Logga in i stället';

  @override
  String get signupScreenNext => 'Nästa';

  @override
  String get signupScreenNotSure => 'Inte säker? Välj \"Jag är förare\".';

  @override
  String get signupScreenPasswordLabel => 'Lösenord';

  @override
  String get signupScreenPasswordMin => 'Minst 8 tecken';

  @override
  String get signupScreenPasswordQuestion => 'Välj ett lösenord';

  @override
  String get signupScreenPhoneLabel => 'Mobil';

  @override
  String get signupScreenPhoneQuestion => 'Ditt mobilnummer';

  @override
  String get signupScreenProblemChoose => 'Välj ett av alternativen.';

  @override
  String get signupScreenProblemCompany => 'Skriv företagets namn.';

  @override
  String get signupScreenProblemEmail =>
      'Det ser inte ut som en e-postadress. Skriv till exempel namn@gmail.com.';

  @override
  String get signupScreenProblemPassword =>
      'Lösenordet behöver minst 8 tecken.';

  @override
  String get signupScreenProblemPhone =>
      'Det ser inte ut som ett mobilnummer. Skriv till exempel 070 123 45 67.';

  @override
  String get signupScreenSoloText => 'Du behöver inget företag.';

  @override
  String get signupScreenSoloTitle => 'Jag är förare';

  @override
  String get signupScreenSomethingWrong => 'Något gick fel. Försök igen.';

  @override
  String signupScreenStepOf(int n, int total) {
    return 'Steg $n av $total';
  }

  @override
  String get signupScreenTitle => 'Prova gratis i en månad';

  @override
  String get signupScreenUnder18 =>
      'En enskild firma registreras av någon som fyllt 18. Kontrollera numret.';

  @override
  String get supportChatEmptyBody =>
      'Skriv din fråga nedan. Du får en notis när vi svarat.';

  @override
  String get supportChatEmptyTitle => 'Hur kan vi hjälpa till?';

  @override
  String get supportChatHint => 'Skriv ett meddelande';

  @override
  String get supportChatLoadFailed =>
      'Kunde inte hämta chatten. Kontrollera nätet.';

  @override
  String get supportChatRetry => 'Försök igen';

  @override
  String get supportChatSend => 'Skicka';

  @override
  String get supportChatSendFailed =>
      'Meddelandet skickades inte. Försök igen.';

  @override
  String get supportChatSubtitle => 'Vi svarar så snart vi kan';

  @override
  String get supportChatTitle => 'Support';

  @override
  String get tipDetailPartsChipCancelled => 'INSTÄLLD';

  @override
  String get tipDetailPartsChipDelayed => 'FÖRSENAD';

  @override
  String tipDetailPartsChipDelayedBy(String delay) {
    return 'FÖRSENAD $delay';
  }

  @override
  String tipDetailPartsNewClock(String clock) {
    return '→ $clock';
  }

  @override
  String get tipReportCancel => 'Avbryt';

  @override
  String get tipReportFailed => 'Kunde inte skicka rapporten. Prova igen.';

  @override
  String get tipReportHint => 'Valfri förklaring';

  @override
  String get tipReportIntro =>
      'Berätta kort vad som inte stämmer, till exempel fel plats eller att störningen redan är löst.';

  @override
  String get tipReportReceived => 'Rapport mottagen — tack.';

  @override
  String get tipReportSend => 'Skicka rapport';

  @override
  String get tipReportThanks => 'Tack — vi granskar tipset.';

  @override
  String get tipReportTitle => 'Rapportera felaktigt tips';

  @override
  String tipSheetAffectedParty(String party) {
    return 'Berörd part: $party';
  }

  @override
  String get tipSheetAlternativeTraffic => 'Alternativ trafik';

  @override
  String get tipSheetCircumstances => 'Särskilda omständigheter';

  @override
  String tipSheetClockAt(String clock) {
    return 'kl $clock';
  }

  @override
  String get tipSheetClose => 'Stäng';

  @override
  String get tipSheetCompensationDisclaimer =>
      'Beloppet gäller när trafikbolagets villkor är uppfyllda. Vi kan inte bedöma den enskilda resan.';

  @override
  String tipSheetCompensationLink(String operator) {
    return 'Läs reglerna hos $operator';
  }

  @override
  String get tipSheetCompensationTitle => 'Taxiersättning';

  @override
  String get tipSheetDriveThere => 'Kör dit';

  @override
  String get tipSheetEnded => 'Slut';

  @override
  String tipSheetEndedAgo(String span) {
    return 'Tog slut för $span sedan';
  }

  @override
  String get tipSheetEndedBanner => 'Slut. Tipset gäller inte längre.';

  @override
  String get tipSheetEndedJustNow => 'Tog slut nyss';

  @override
  String get tipSheetGotFare => 'Fick körning';

  @override
  String get tipSheetHide => 'Dölj';

  @override
  String tipSheetLineTo(String line, String to) {
    return '$line → $to';
  }

  @override
  String get tipSheetMinorNote =>
      'Allmänt meddelande. Vi bedömer inte om det är värt att köra dit.';

  @override
  String get tipSheetNavFailed => 'Kunde inte öppna navigeringen.';

  @override
  String get tipSheetNoCustomer => 'Ingen kund';

  @override
  String get tipSheetNoDescription =>
      'Ingen ytterligare beskrivning tillgänglig.';

  @override
  String get tipSheetOpenNavigation => 'Öppna navigering';

  @override
  String get tipSheetOperatorFallback => 'trafikbolaget';

  @override
  String get tipSheetReadMore => 'Läs mer';

  @override
  String get tipSheetReported => 'Rapporterat';

  @override
  String get tipSheetRoadAdvice => 'Räkna med kö, eller välj en annan väg.';

  @override
  String get tipSheetSave => 'Spara tipset';

  @override
  String get tipSheetSectionEvent => 'Händelse & beskrivning';

  @override
  String get tipSheetSectionNotice => 'Trafikbolagets meddelande';

  @override
  String get tipSheetSectionRoad => 'Vägen dit';

  @override
  String get tipSheetShowAllReasons => 'Visa alla skäl';

  @override
  String get tipSheetShowFewerReasons => 'Visa färre skäl';

  @override
  String get tipSheetShowFullText => 'Visa hela texten';

  @override
  String get tipSheetShowLess => 'Visa mindre';

  @override
  String get tipSheetSourcePage => 'Trafikbolagets sida';

  @override
  String tipSheetStartedAgo(String span) {
    return 'Började för $span sedan';
  }

  @override
  String get tipSheetStartedJustNow => 'Började nyss';

  @override
  String tipSheetStartsIn(String span) {
    return 'Börjar om $span';
  }

  @override
  String get tipSheetStartsNow => 'Börjar nu';

  @override
  String get tipSheetStatusNotice => 'MEDDELANDE';

  @override
  String get tipSheetStatusStopped => 'STOPP I TRAFIKEN';

  @override
  String get tipSheetTaxiPaid => 'Taxi betalas';

  @override
  String get tipSheetUnsave => 'Ta bort sparat';

  @override
  String get trialWelcomeAllIncluded => 'Allt ingår just nu.';

  @override
  String get trialWelcomeClose => 'Stäng';

  @override
  String get trialWelcomeColorNote =>
      'Färgen visar hur stark signalen är. En stark signal betyder att många sannolikt behöver taxi.';

  @override
  String get trialWelcomeCostsNothing => 'Det kostar inget att prova.';

  @override
  String trialWelcomeDate(int day, String month) {
    String _temp0 = intl.Intl.selectLogic(month, {
      '1': 'januari',
      '2': 'februari',
      '3': 'mars',
      '4': 'april',
      '5': 'maj',
      '6': 'juni',
      '7': 'juli',
      '8': 'augusti',
      '9': 'september',
      '10': 'oktober',
      '11': 'november',
      '12': 'december',
      'other': '',
    });
    return '$day $_temp0';
  }

  @override
  String get trialWelcomeDone => 'Klar';

  @override
  String trialWelcomeFreeDays(int days) {
    String _temp0 = intl.Intl.pluralLogic(
      days,
      locale: localeName,
      other: 'Gratis i $days dagar.',
      one: 'Gratis i $days dag.',
    );
    return '$_temp0';
  }

  @override
  String get trialWelcomeFreeToTry => 'Gratis att prova.';

  @override
  String trialWelcomeFreeUntil(String date) {
    return 'Gratis till $date.';
  }

  @override
  String get trialWelcomeIncludedHeading => 'Ingår i provet';

  @override
  String get trialWelcomeIncludedTitle => 'Vad ingår i provet?';

  @override
  String get trialWelcomeIncludedUnknown =>
      'Det som ingår i provet ser du i appen. Det som inte ingår har ett lås.';

  @override
  String get trialWelcomeLineEvent =>
      'Event som slutar: match, konsert eller annat.';

  @override
  String get trialWelcomeLineFerry => 'Färjor som lägger till i hamnen.';

  @override
  String get trialWelcomeLineFlight =>
      'Flyg som är sena, eller när många flyg landar.';

  @override
  String get trialWelcomeLineRoad => 'Trafikolyckor som stoppar trafiken.';

  @override
  String get trialWelcomeLineTransit =>
      'Tåg och buss som är sena eller inställda. Sista avgången.';

  @override
  String trialWelcomeNeedsMembership(String onWeb) {
    return 'Det kräver medlemskap. $onWeb';
  }

  @override
  String get trialWelcomeNext => 'Nästa';

  @override
  String get trialWelcomeOneSeat => 'Du kan ha 1 plats i provet, med ett län.';

  @override
  String trialWelcomePageOf(int page, int total) {
    return 'Sida $page av $total';
  }

  @override
  String get trialWelcomeReadyTitle => 'Klart! Du är igång';

  @override
  String trialWelcomeSeats(int limit) {
    String _temp0 = intl.Intl.pluralLogic(
      limit,
      locale: localeName,
      other: 'Du kan ha upp till $limit platser i provet.',
    );
    return '$_temp0';
  }

  @override
  String get trialWelcomeShowTips => 'Visa tipsen';

  @override
  String get trialWelcomeSkip => 'Hoppa över';

  @override
  String get trialWelcomeStep1Text =>
      'Öppna Inställningar och tryck på Dina län. Länet styr vilka tips du får.';

  @override
  String get trialWelcomeStep1Title => 'Byt län';

  @override
  String get trialWelcomeStep2Text =>
      'Inbjudan skickas av företagets administratör på webben, inte från appen. Föraren får ett mejl, väljer ett lösenord och loggar in i appen med e-post och lösenord.';

  @override
  String get trialWelcomeStep2Title =>
      'Har du ett taxibolag? Bjud in förare på webben';

  @override
  String get trialWelcomeStepsTitle => 'Så kommer du igång';

  @override
  String trialWelcomeTrialEnded(String onWeb) {
    return 'Provet är slut. $onWeb';
  }

  @override
  String trialWelcomeTrialRunning(String date) {
    return 'Provet pågår. Det gäller till $date.';
  }

  @override
  String get trialWelcomeTrialStarts =>
      'Provet startar när första föraren loggar in.';

  @override
  String get trialWelcomeTrialStartsPending =>
      'Provet startar när första föraren loggar in. Tills dess går ingen tid.';

  @override
  String trialWelcomeTrialTitleDays(int days) {
    String _temp0 = intl.Intl.pluralLogic(
      days,
      locale: localeName,
      other: 'Du provar gratis i $days dagar',
      one: 'Du provar gratis i $days dag',
    );
    return '$_temp0';
  }

  @override
  String get trialWelcomeTrialTitleNoDays => 'Du provar gratis';

  @override
  String get trialWelcomeWatching => 'Vi bevakar';

  @override
  String get trialWelcomeWhatBody =>
      'Taxi Tips visar var folk kan behöva taxi just nu. Det är tips, inte löften. Du bestämmer själv om det är värt att åka.';

  @override
  String get trialWelcomeWhatTitle => 'Välkommen till Taxi Tips';

  @override
  String get vehicleSessionAnotherPhone => 'en annan telefon';

  @override
  String get vehicleSessionCancel => 'Avbryt';

  @override
  String get vehicleSessionCar => 'Bil';

  @override
  String vehicleSessionCountiesCount(int count) {
    return '$count län';
  }

  @override
  String get vehicleSessionDrive => 'Kör';

  @override
  String get vehicleSessionLeave => 'Lämna bilen';

  @override
  String get vehicleSessionNoVehicles =>
      'Telefonen är inte kopplad till någon bil. Be din chef bjuda in dig med din e-post, och logga in som förare.';

  @override
  String get vehicleSessionSubtitle =>
      'Tipsen gäller bilens län. En bil kan bara ha en telefon åt gången.';

  @override
  String get vehicleSessionTakeOver => 'Ta över';

  @override
  String vehicleSessionTakeOverBody(String message) {
    return '$message\n\nDen andra telefonen slutar visa tips för den här bilen direkt.';
  }

  @override
  String get vehicleSessionTakeOverCar => 'Ta över bilen';

  @override
  String vehicleSessionTakeOverTitle(String plate) {
    return 'Ta över $plate?';
  }

  @override
  String get vehicleSessionTheCar => 'bilen';

  @override
  String get vehicleSessionTitle => 'Vilken bil kör du?';

  @override
  String vehicleSessionUsedBy(String name) {
    return 'Används av $name';
  }

  @override
  String get vehicleSessionYouDriveThis => 'Du kör den här';

  @override
  String get welcomeScreenBrowserFailed => 'Kunde inte öppna webbläsaren';

  @override
  String get welcomeScreenCreateAccount => 'Skapa konto gratis';

  @override
  String get welcomeScreenHeadline => 'Se var folk behöver taxi';

  @override
  String get welcomeScreenLogin => 'Logga in';

  @override
  String get welcomeScreenSeeDemo => 'Se demon på webben';
}
