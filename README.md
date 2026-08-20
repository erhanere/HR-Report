# Resmi Gazete Günlük Özet

Her gün saat **09:00 (Europe/Istanbul)**'da [Resmi Gazete](https://www.resmigazete.gov.tr/)'nin
o günkü sayısını çeker, Claude ile Türkçe bir özet e-postası oluşturur ve
[Resend](https://resend.com) üzerinden gönderir. GitHub Actions ile çalışır,
sunucu gerektirmez.

## Nasıl çalışır

1. `.github/workflows/daily-digest.yml` her gün 06:00 UTC'de (İstanbul'da 09:00,
   Türkiye yaz saati uygulamadığı için ofset sabit) tetiklenir.
2. `scripts/daily_digest.py`:
   - `https://www.resmigazete.gov.tr/eskiler/YYYY/MM/YYYYMMDD.htm` adresini indirir,
   - Sayfayı kategori başlığı → madde listesi şeklinde ayrıştırır (başlık heuristiği;
     sitenin CSS sınıfları garanti olmadığı için üst-başlık + altındaki linkler mantığıyla çalışır),
   - Ayrıştırılan ham listeyi Claude'a (Anthropic API) vererek "Öne Çıkanlar" +
     kategori bazlı gruplu, kısa Türkçe bir HTML e-posta gövdesi oluşturtur,
   - Resend API ile e-postayı gönderir.
3. Ayrıştırılan ham veri her çalıştırmada `gazette_items.json` adıyla workflow
   artifact'i olarak saklanır — parse mantığı bir gün beklenmedik çıktı verirse
   (site tasarımı değişirse) buradan teşhis edebilirsiniz.

## Kurulum

Repo **Settings → Secrets and variables → Actions** altında aşağıdakileri ekleyin:

### Secrets
| Ad | Açıklama |
|---|---|
| `ANTHROPIC_API_KEY` | Özetleri üretmek için Anthropic API anahtarı |
| `RESEND_API_KEY` | E-posta göndermek için Resend API anahtarı |

### Variables
| Ad | Açıklama |
|---|---|
| `DIGEST_TO_EMAIL` | Alıcı adresi (örn. `erhane@koc.com.tr`) |
| `DIGEST_FROM_EMAIL` | Gönderen adresi. Resend'de doğrulanmış bir alan adınız yoksa test için `onboarding@resend.dev` kullanılabilir, ama bu durumda **yalnızca Resend hesabınızın sahibi olduğu e-posta adresine** gönderim yapılabilir. Kendi alan adınızı Resend'de doğrularsanız (`Domains` sekmesi) istediğiniz `from` adresini kullanabilirsiniz. |

### Resend kurulumu
1. [resend.com](https://resend.com) üzerinde ücretsiz hesap açın.
2. API key oluşturun → `RESEND_API_KEY` secret'ı olarak ekleyin.
3. `erhane@koc.com.tr` adresine düzenli gönderim için, gönderen tarafında kendi
   alan adınızı (örn. `koc.com.tr` ya da onun bir alt alanı) Resend'de doğrulamanız
   önerilir; aksi halde sandbox modunda gönderim kısıtlı olur.

## Test etme

Cron beklemeden manuel tetiklemek için: **Actions → Resmi Gazete Daily Digest →
Run workflow**. İsteğe bağlı olarak `gazette_date` girdisiyle geçmiş bir tarihi
test edebilirsiniz (`YYYY-MM-DD`).

Yerel olarak test etmek için:

```bash
pip install -r requirements.txt
export TO_EMAIL=erhane@koc.com.tr
export FROM_EMAIL=onboarding@resend.dev
export RESEND_API_KEY=...
export ANTHROPIC_API_KEY=...
python scripts/daily_digest.py
```

## Bilinen sınırlamalar

- Sayfa ayrıştırma, resmigazete.gov.tr'nin HTML yapısına dayalı bir sezgisel
  yöntemle (başlık satırları + altlarındaki linkler) çalışır; sitenin tasarımı
  değişirse ayarlama gerekebilir. `gazette_items.json` artifact'i bu durumda
  ilk kontrol noktanız olmalı.
- Özetler madde **başlıklarına** dayanır, PDF/HTML tam metinleri indirip
  okumaz — bu, hız ve maliyeti düşük tutar ama özetler bazen genel kalabilir.
- Resmi Gazete'nin yayımlanmadığı bir gün olursa (çok nadir), script bunu
  tespit edip durumu bildiren kısa bir e-posta gönderir.
