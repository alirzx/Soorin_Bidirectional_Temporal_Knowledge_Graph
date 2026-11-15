# گزارش ادامهٔ سخت‌سازی Soorin TKG — ۲۰۲۶-۱۱-۱۵

این گزارش ادامهٔ کار قبلی است. شاخهٔ `main` حفظ شد؛ پنج commit منتشرشده بازنویسی
نشدند. در این نوبت هیچ build محلی، نصب یا دانلود، راه‌اندازی Docker، migration
محلی، بارگذاری مدل، تماس با provider یا E2E زنده اجرا نشد. نتیجه، تحویل کد برای
مرحلهٔ ساختِ جداگانه است؛ `FULL_E2E_VERIFIED=false`.

## وضعیت مخزن و دامنه

- مخزن قابل‌نوشتن: `alirzx/Soorin_Bidirectional_Temporal_Knowledge_Graph`؛ شاخه `main`.
- baseline اولیه: `b98b0c4407701ff6848749538e2b867776dc0121`.
- ابتدای ادامه: `efee3b2a2a4bd21169cbdbfcd328a1a46811374b`؛ پنج commit قبلی از قبل روی `personal/main` بودند.
- تنها مقصد push، ریموت شخصی است. tracking شاخه به `origin/main` تغییر داده نشد؛ ahead بودن نسبت به origin به معنای منتشرنشدن روی personal نیست.
- تغییرات ناتمام چهار فایل صف ابتدا در `/tmp` حفظ و سپس بازبینی و commit شدند.
- Agentic_SOC فقط برای قرارداد خوانده شد؛ HEAD آن `a0a160d1dfbd83304fbb335b8ef8ba871a04cd90` و worktree آن بدون تغییر ماند.
- هیچ migration قبلی تغییر نکرد؛ تنها SQL جدید نسبت به baseline، `10004_soorin_chat_read_timeout.sql` است. شمار فایل‌های SQL و نسخهٔ manifest اکنون ۱۰۵ است.

SHA نهایی، نتیجهٔ push و CI دقیق همان SHA در گزارش پایان گفت‌وگو ثبت می‌شود؛ این
فایل برای جلوگیری از ادعای خودارجاع، SHA مربوط به commit شامل خودش را حدس نمی‌زند.

## بازبینی پنج commit قبلی

| Commit | رفتار پیاده‌شده | یافته و اصلاح ادامه | شاهد و ریسک باقی‌مانده |
|---|---|---|---|
| `48a6526` | batch/window بردار و انتظار CPU | pooling عمومی برای همهٔ providerها مناسب نبود؛ فقط شناسهٔ دقیق BGE pin‌شده آن را انتخاب می‌کند. تعداد threadهای خواندن درخواست نیز محدود شد؛ ورودی نامعتبر پیش از صف/بارگذاری رد می‌شود | آزمون wire برای ۶۴ ورودی، ترتیب و پنجره؛ mock ظرفیت/لغو/ورودی؛ کیفیت centroid و inference واقعی هنوز سنجیده نشده |
| `9354190` | پیمایش array و OCSF رشته‌ای | scope تو‌در‌تو، payload تو‌در‌تو، array مختلط و `{type,value}` واقعی fusion پوشش داده شد؛ JSON مبهم رد می‌شود | آزمون‌های استخراج/قرارداد؛ مخزن تولیدکننده فقط خوانده شد |
| `eed32b6` | Deferred، ترتیب revision، diagnostics و curated API | diagnostics قدیمی نسخهٔ شاهد را مثل gate بررسی نمی‌کرد؛ اکنون query مشترک است. نوع/پیوند entity، terminal predecessor/document و رد انسانی روشن شد. مسیر import فرایند Python نیز صریح شد | آزمون API/DB در CI؛ اجرای image واقعی و cancellation زنده باقی است |
| `daec611` | endpoint/model/key/reasoning/timeout | نسخهٔ schema همراه migration افزایش نیافته بود؛ ۱۰۵ شد. URL حاوی credential/query/fragment و انتقال کلید قدیمی به origin جدید رد شد | unit/mock تنظیمات و CI؛ credential/provider/Gateway واقعی آزمایش نشده |
| `efee3b2` | assertionهای native و اصلاح password Make | assertion فقط predicate برای دو سر رابطه کافی نبود؛ هویت دو سر، source scope، نوع، نسخه و شاهد اضافه شد. RNG failure و overwrite race نیز fail closed شد | آزمون مصنوعی و فایل موقت؛ harness زنده اجرا نشد |

## ریشه‌یابی و اصلاحات تأییدشده

| دسته | مشکل / شاهد | اصلاح و آزمون |
|---|---|---|
| CONFIRMED_ROOT_CAUSE | CI `43595919301` در CLI: `CURRENT_SCHEMA_VERSION` برابر ۱۰۴ و شمار migrations برابر ۱۰۵ بود | افزایش constant بدون migration اضافی؛ سیاست restore جدیدتر=رد، قدیمی‌تر=هشدار حفظ شد |
| CONFIRMED_ROOT_CAUSE | ثبت نتیجهٔ job در خطای موقت DB فقط log می‌شد؛ ack قدیمی بدون claim fence امکان overwrite داشت | port انتخابی upstream `b7f756e`؛ نگهداری نتیجهٔ محاسبه‌شده، retry همان writeback، شرط `running + locked_at`؛ آزمون fault injection، ack تکراری، claim قدیمی و pool بسته |
| CONFIRMED_ROOT_CAUSE | پس از عبور CLI، CI `43681293225` برای preview از cwd مربوط به crate، ۴۲۲ داد؛ module import به cwd وابسته بود | `python3 -S` با `PYTHONPATH` صریح، default image `/app` و root آزمون؛ subprocess از cwd نامرتبط بدون site-packages نیز پاس شد |
| CONFIRMED_CONTRACT_MISMATCH | سیاست pooling روی shared embedding client همهٔ providerها اعمال می‌شد | حفظ request/vector اصلی provider عمومی؛ BGE دقیقاً pin‌شده: batch<=16، window<=16000، wire<=280000، dimension=1024 و finite/nonzero؛ pooling یک تقریب retrieval مستند است |
| CONFIRMED_ROOT_CAUSE | SQL diagnostics می‌توانست شاهد نسخهٔ قبلی را موفق نشان دهد؛ assertion harness دو سر رابطه را مقایسه نمی‌کرد | query مشترک typed/current-version، multiset predicate+subject+object، document/version و authority checks |
| CONFIRMED_CONTRACT_MISMATCH | fusion واقعاً `entities/iocs` از نوع `{type,value}` و OCSF از نوع JSON-string تولید می‌کند | واژگان دقیق و اعتبارسنجی IP/hash/domain/URL؛ حفظ path و scope؛ نوع ناشناخته authoritative نمی‌شود |
| REPRODUCED_BUG | fixture آفلاین نشان داد retrieval پیش‌فرض نسخهٔ invalidated را همراه نسخهٔ اصلاح‌شده برمی‌گرداند؛ timestampها شکل یکسان نداشتند | normalization زمان و حذف invalidated در نمای جاری؛ مرز نیمه‌باز knowledge time و fixture دوزبانه/tenant/evidence |
| CONFIGURATION_GAP | Star History از `secrets.METRICS_TOKEN` استفاده می‌کند و secret موجود نیست | مستقل از CI اصلی؛ نیازمند secret مجاز در GitHub. token، مجوز یا trigger تضعیف/جعل نشد |
| NOT_REPRODUCED | Context قبلی پس از resolution بدون UUID، ۴۲۲ و MCP بدون PAT اثبات‌شده، ۴۰۱ داده بود | هیچ auth یا validation برای پنهان‌کردن این خطاها شل نشد؛ آزمون زنده با ورودی/credential معتبر در handoff |

انتظارهای SOC هر ۱۵ ثانیه با Deferred زمان‌بندی می‌شوند؛ مهلت انتظار صف یک ساعت
است و پس از آن بودجهٔ خطای محدود اعمال می‌شود. lease دو دقیقه و handler نود ثانیه
است. predecessor تمام‌شده/ناموفق، سند شکست‌خورده بدون retry فعال و binding ردشدهٔ
انسانی failure code مشخص دارند. رسید در انتظار به‌صورت کاذب `bound` نمی‌شود.
صف همچنان همان صف PostgreSQL است و recovery شروع کار هنوز فرض یک process برنامه را دارد.

## شواهد آزمون و محدودیت اجرا

- آزمون‌های سبک Python: **۱۸۶ آزمون موفق**، به‌اضافهٔ **۷ آزمون mock Splunk موفق**؛ extraction، identity، temporal، retrieval، privacy، configuration، CPU mock، adapter subprocess، native assertions و Make در فایل موقت؛ بدون وزن یا سرویس واقعی.
- AST هر ۹۹ فایل Python و parse هر ۱۱ فایل JSON موفق بود؛ لینک‌های محلی Markdown، immutable بودن تمام SQLهای baseline، shell syntax و سه ترکیب Compose با `config --quiet` تأیید شد. env واقعی یا secret در خروجی چاپ نشد.
- Graphify به‌صورت AST-only refresh شد؛ graph/cache commit نشده است. نبود `tree_sitter_sql` ثبت شد و dependency نصب نشد؛ روابط SQL حساس مستقیماً در source بازبینی شدند.
- formatter بومی قابل‌استفاده روی میزبان وجود ندارد؛ binary cache فاقد rustc driver است. هیچ container یا toolchain برای آن شروع/نصب نشد. diff دقیق formatter خود CI اعمال شد.
- Rust fmt/Clippy/build/test و migrations محلی: **NOT RUN — deferred to controlled build phase**.
- frontend محلی: **NOT RUN**؛ این patch کد frontend را عوض نکرده است؛ شاهد CI جداست.
- CI اولیه `efee3b2`: lint/web/Python/build/migrations موفق، test به علت schema count ناموفق؛ پس از رفع آن import curated آزمون شکست خورد.
- CI کد `b83e4c3c3bcdab4ec288d3460ef0d71bffa310a7`، run `43682559008`: **تمام jobهای اصلی موفق**؛ lint، test، build، migrations، web، python-foundation، backend.
- این CI شامل fixture پایگاه داده، مسیر native/typed/current-version و آزمون‌های writeback است؛ موفقیت آن معادل اجرای image جدید یا E2E با مدل‌های واقعی نیست.
- SHA نهایی شامل مستندات و آخرین regressionهای Python/API است؛ نتیجهٔ CI همان SHA باید پس از push مجدداً خوانده شود و در پاسخ نهایی گزارش شود.

## دامنهٔ ۱۹ وظیفه و آمادگی

[ماتریس کامل ۱۹ وظیفه](CONTINUATION_TASK_MATRIX.md) فایل‌ها، وضعیت و gate باقی‌مانده
را تفکیک می‌کند. استخراج و audit قرارداد تولیدکننده و تنظیمات QA در دامنهٔ source/unit
تکمیل شدند. پذیرش ingestion، گراف، identity، مدل، context، MCP و Agent همچنان به
آزمون runtime مربوط است. Chat واقعی علاوه بر runtime به تنظیمات بیرونی نیاز دارد.

Dockerfile برنامه Python استاندارد و کد/ontology را برای UID 65532 فراهم می‌کند.
Compose production پورت DB/model را منتشر نمی‌کند و image digest/secretهای نمونه
placeholder باقی مانده‌اند. TTL و محدودیت ۳۰ثانیه‌ای مرحلهٔ Gateway با idle timeout
workspace یکی نیست. این تفاوت مستند شد؛ privacy fail closed و نبود fallback خام حفظ شد.

- Native ingestion، typed graph، evidence، temporal و exact identity: پیاده‌سازی و regression؛ پذیرش image زنده باقی است.
- BM25/dense/reranker: fixture و مسیر اجرای موجود؛ کیفیت واقعی و latency/RAM هنوز تأیید نشده.
- NER: فقط proposal/review؛ precision/recall مدل واقعی تأیید نشده.
- MCP: یازده ابزار read؛ `remember` موجود فقط با PAT write و نقش editor؛ تست PAT واقعی باقی است.
- Native Agent و DeepSeek/Arvan: قرارداد و mock؛ endpoint/model/key مجاز، Gateway و grounding واقعی باقی است. هیچ اجرای زندهٔ Agentic_SOC ادعا نمی‌شود.
- PostgreSQL/backup: schema ۱۰۵ و migration CI؛ تست upgrade/restore و نقش واقعی deployment در نوبت بعد.

## تحویل مرحلهٔ بعد

دستورهای دقیق و ترتیب در [NEXT_APPROVED_BUILD_20261115.md](NEXT_APPROVED_BUILD_20261115.md)
است: preflight → migration verification → build محدود → startup → cache verification
→ مدل → native E2E → temporal/retrieval → MCP → privacy/Chat → پذیرش release.
تنظیمات مدل و API در [MODEL_CONFIGURATION.md](MODEL_CONFIGURATION.md) و
[MANUAL_SOC_INGESTION.md](MANUAL_SOC_INGESTION.md)، مشخصات OpenAPI در
[curated_http_v1.openapi.json](../../soorin/contracts/schemas/curated_http_v1.openapi.json)
و قرارداد تولیدکننده در [mapping v1](PRODUCER_MAPPING_V1_20261115.md) آمده است.

حکم دامنهٔ این نوبت: **SOURCE_PATCH_COMPLETE / READY_FOR_NEXT_LOCAL_BUILD**،
مشروط به موفقیت بررسی نهایی SHA/push/CI گزارش‌شده در پایان گفت‌وگو.
**FULL_E2E_VERIFIED=false**؛ آمادگی production ادعا نمی‌شود.

## فهرست commitهای ادامه تا پیش از commit مستندات

```text
c94f3b20b38969af8fbe2a5376762f8b8fb15b58 fix(migrations): synchronize backup schema version with chat timeout migration
a7c021033d25835421ff4baaaa84e4ec83966eac fix(jobs): fence acknowledgements and retry computed outcomes safely
093e691a733f98c6cb3f51cbe6835c00adb9bf80 fix(models): scope window pooling and bound request handler capacity
1f087bb599e23ab0a4932979705989299a1c4ac0 fix(soc-extraction): validate nested authority and fusion typed values
1f3e75293c4b52d2ec1ec0e95672eee7df70d1c0 fix(soc-api): make adapter imports explicit and separate input failures
22322315c39c25c70d7047e79409f34259a9345f fix(soc): align receipt gates with exact current-version evidence
e5eb4dcf404c14d8658a95bd090641a6b53e935d fix(config): reject credential URLs and cross-origin secret reuse
4690f111908404d19d7df10f766355801cd71586 fix(qa): fail closed on secret generation and preserve existing env files
37565e2f272d3138c6d7b15eb8ad99ec0721b96b fix(evaluation): preserve current and historical retrieval boundaries
b83e4c3c3bcdab4ec288d3460ef0d71bffa310a7 style(rust): apply formatter output from automatic CI
dda593844ef2d733e730d07f92fc11cf6152741b test(soc): isolate acceptance settings with existing QA sessions
ad388d684ac5278d63df2573e70c7da89534d128 test(soc-api): cover curated receipt replay and nested JSON ambiguity
```

Commit نهایی مستندات و SHA نهایی در گزارش پایان گفت‌وگو آمده است.
