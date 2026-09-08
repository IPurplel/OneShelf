# Noor anonymous-reader captures

Captured 2026-09-08 UTC from the live site over the app's local desync proxy,
using its default User-Agent and an initially empty HTTP cookie jar. No account,
password, browser login, or Download endpoint was used.

- `book.html`: GET `https://www.noor-book.com/en/ebook-الليالي-البيضاء-دوستويفسكي-pdf`.
- `anonymous.json`: POST `/en/Verification/check_user` with the anonymous setup
  fields from that page. The response explicitly reports `is_logged: 0`.
- `reader.html`: POST `/en/book/read_book` with that anonymous session's cookies,
  CSRF and local-storage values. Contains the 111-page enumeration.
- `search.html`: GET `https://www.noor-book.com/en/tag/White%20Nights`.
- `negative.html`: GET `https://www.noor-book.com/en/tag/zzqvoneshelfnonexistent987654321`.

The search pages contain unrelated recommendations even for the nonsense query;
the existing relevance gate must keep the negative result empty. Anonymous
anti-forgery values in captures are not account credentials and are not reused
for live requests. Every live request obtains a fresh anonymous session.
