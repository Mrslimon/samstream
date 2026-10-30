export type Language = "en" | "ar";

export interface Strings {
  off: string;
  home: string;
  liveTv: string;
  inputList: string;
  tvCorner: string;
  power: string;
  cameras: string;
  showCamera: string;
  stop: string;
  message: string;
  messagePlaceholder: string;
  title: string;
  duration: string;
  seconds: string;
  showMessage: string;
  updateText: string;
  info: string;
  warning: string;
  alert: string;
  apps: string;
  remote: string;
  media: string;
  tv: string;
  sections: string;
  camerasField: string;
  keyboard: string;
  touchpad: string;
  typeHere: string;
  send: string;
  leftClick: string;
  rightClick: string;
  touchpadHint: string;
  keyboardNote: string;
  touchpadNote: string;
  back: string;
  menu: string;
  ok: string;
  volumeDown: string;
  volumeUp: string;
  volume: string;
  mute: string;
  playPause: string;
  noCameras: string;
  sent: string;
  failed: string;
  art: string;
  artUpload: string;
  artBorder: string;
  artNoBorder: string;
  artApply: string;
  artCropHint: string;
  artSharp: string;
  artFine: string;
  artSoft: string;
  artOnTv: string;
  artCancel: string;
  artUploadShow: string;
  artUploading: string;
  artUploaded: string;
  artFailed: string;
  artNotPicture: string;
}

const STRINGS: Record<Language, Strings> = {
  en: {
    off: "Off",
    home: "Home",
    liveTv: "Live TV",
    inputList: "Inputs",
    tvCorner: "Keep Live TV / HDMI in a corner",
    power: "Power",
    cameras: "Cameras",
    showCamera: "Show on TV",
    stop: "Stop",
    message: "Message",
    messagePlaceholder: "Text to show on the TV",
    title: "Title",
    duration: "Duration",
    seconds: "s",
    showMessage: "Full-screen message",
    updateText: "Update text",
    info: "Info",
    warning: "Warning",
    alert: "Alert",
    apps: "Apps",
    remote: "Remote",
    media: "Playback and volume",
    tv: "TV and power",
    sections: "Sections (drag to reorder)",
    camerasField: "Cameras (empty: all)",
    keyboard: "Keyboard",
    touchpad: "Touchpad",
    typeHere: "Open a text field on the TV, then type here",
    send: "Send",
    leftClick: "Click",
    rightClick: "Right click",
    touchpadHint: "Drag to move · tap to click · hold for right click",
    keyboardNote: "Works with the TV's own keyboard (browser, sign-in fields). Apps with their own keyboard, like YouTube, ignore it.",
    touchpadNote: "For the web browser and apps with a pointer; elsewhere the TV shows its pointer panel instead.",
    back: "Back",
    menu: "Menu",
    ok: "OK",
    volumeDown: "Volume down",
    volumeUp: "Volume up",
    volume: "Volume",
    mute: "Mute",
    playPause: "Play / pause",
    noCameras: "No cameras in Home Assistant yet.",
    sent: "Sent to the TV",
    failed: "Failed",
    art: "Art",
    artUpload: "Add picture",
    artBorder: "Frame border",
    artNoBorder: "None",
    artApply: "Apply border",
    artCropHint: "Drag to choose the part to show; zoom in for less. The dimmed part will not be on the TV.",
    artSharp: "Sharp on the 4K screen",
    artFine: "Fine, slightly enlarged",
    artSoft: "Low resolution: it will look soft",
    artOnTv: "On the TV",
    artCancel: "Cancel",
    artUploadShow: "Upload and show",
    artUploading: "Uploading…",
    artUploaded: "Added to My Photos and shown on the TV",
    artFailed: "Could not reach the Frame's art gallery",
    artNotPicture: "That file is not a picture this browser can open",
  },
  ar: {
    off: "مطفأ",
    home: "الرئيسية",
    liveTv: "البث المباشر",
    inputList: "المدخلات",
    tvCorner: "إبقاء البث المباشر / HDMI في الزاوية",
    power: "التشغيل",
    cameras: "الكاميرات",
    showCamera: "اعرض على التلفاز",
    stop: "إيقاف",
    message: "الرسالة",
    messagePlaceholder: "نص يظهر على التلفاز",
    title: "العنوان",
    duration: "المدة",
    seconds: "ث",
    showMessage: "رسالة بملء الشاشة",
    updateText: "تحديث النص",
    info: "معلومة",
    warning: "تحذير",
    alert: "تنبيه",
    apps: "التطبيقات",
    remote: "جهاز التحكم",
    media: "التشغيل والصوت",
    tv: "التلفاز والتشغيل",
    sections: "الأقسام (اسحب لإعادة الترتيب)",
    camerasField: "الكاميرات (فارغ: الكل)",
    keyboard: "لوحة المفاتيح",
    touchpad: "لوحة اللمس",
    typeHere: "افتح حقل نص على التلفاز ثم اكتب هنا",
    send: "إرسال",
    leftClick: "نقر",
    rightClick: "نقر أيمن",
    touchpadHint: "اسحب للتحريك · انقر للنقر · اضغط مطولًا للنقر الأيمن",
    keyboardNote: "يعمل مع لوحة مفاتيح التلفاز (المتصفح وحقول تسجيل الدخول). التطبيقات ذات لوحة المفاتيح الخاصة مثل يوتيوب تتجاهله.",
    touchpadNote: "للمتصفح والتطبيقات التي تعرض مؤشرًا؛ في غيرها يعرض التلفاز لوحة المؤشر الخاصة به.",
    back: "رجوع",
    menu: "القائمة",
    ok: "موافق",
    volumeDown: "خفض الصوت",
    volumeUp: "رفع الصوت",
    volume: "مستوى الصوت",
    mute: "كتم",
    playPause: "تشغيل / إيقاف مؤقت",
    noCameras: "لا توجد كاميرات في Home Assistant بعد.",
    sent: "أُرسل إلى التلفاز",
    failed: "فشل",
    art: "الفن",
    artUpload: "إضافة صورة",
    artBorder: "إطار الصورة",
    artNoBorder: "بلا إطار",
    artApply: "تطبيق الإطار",
    artCropHint: "اسحب لاختيار الجزء الذي يظهر، وكبّر لإظهار جزء أصغر. الجزء المعتم لن يظهر على التلفاز.",
    artSharp: "واضحة على شاشة 4K",
    artFine: "جيدة، مكبّرة قليلًا",
    artSoft: "دقة منخفضة: ستبدو غير حادة",
    artOnTv: "على التلفاز",
    artCancel: "إلغاء",
    artUploadShow: "رفع وعرض",
    artUploading: "جارٍ الرفع…",
    artUploaded: "أُضيفت إلى صوري وعُرضت على التلفاز",
    artFailed: "تعذّر الوصول إلى معرض الفن في Frame",
    artNotPicture: "هذا الملف ليس صورة يستطيع المتصفح فتحها",
  },
};

export function languageOf(code: string | undefined): Language {
  return code?.toLowerCase().startsWith("ar") ? "ar" : "en";
}

export function strings(language: Language): Strings {
  return STRINGS[language];
}

export const LANGUAGES = Object.keys(STRINGS) as Language[];
