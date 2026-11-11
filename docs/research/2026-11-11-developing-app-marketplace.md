# Developing App Marketplace: biên soạn chi tiết và trả lời 5 câu hỏi

- Ngày: 2026-11-11. Vai: Research + Decision. Người yêu cầu: Hùng (thread "Biên soạn dự án Developing App Marketplace").
- Đầu vào: `Developing-App-Marketplace-Business-Blueprint.md` v1.0 và `AI-Compute-Marketplace-Pre-Feasibility-Study.md` v1.0 (Hùng gửi 2026-11-11), Roadmap LFMAP, `docs/research/2026-11-10-lanhai-assistant-architecture.md`, `docs/research/2026-11-08-architecture-review.md`.
- Trạng thái: **tài liệu nghiên cứu, chưa có quyết định nào được chốt.** Không đổi ADR, Roadmap hay Blueprint. Không có task nào được xếp lịch. Các điểm cần Hùng quyết nằm ở mục 9.
- Ngôn ngữ: tiếng Việt vì đây là tài liệu kinh doanh để Hùng đọc và quyết (khác quy ước tiếng Anh cho spec kỹ thuật).
- Giới hạn của tài liệu:
  - Tra cứu web làm ngày 2026-11-11 từ phiên Cloud. Phần lớn nguồn là **nguồn thứ cấp** (bài báo, blog so sánh, trang tư vấn luật), một số do chính đối thủ viết. Mỗi dữ kiện có nhãn: **[đã tra]** = có nguồn thứ cấp, link ở mục 10; **[chưa kiểm]** = từ trí nhớ hoặc suy luận, kèm cách kiểm.
  - Không mở được `comatch.vn` từ phiên Cloud (bị chặn mạng), chỉ đọc được đoạn mô tả qua công cụ tìm kiếm.
  - Phần pháp lý **không phải tư vấn pháp lý**. Mọi kết luận pháp lý phải được luật sư xác nhận trước khi hành động (mục 7.4 có danh sách câu hỏi mang đi hỏi).
  - Các con số tài chính ở mục 6 là **ví dụ minh hoạ để thấy độ lớn**, không phải dự báo.

## 1. Tóm tắt (đọc phần này trước)

1. **Bảng đăng tin không phải là điểm khác biệt.** Ở Việt Nam đã có ít nhất một nền tảng làm gần đúng nội dung blueprint (CoMatch: bán sản phẩm số, tìm đồng hành góp vốn hoặc góp công, đăng miễn phí, thu phí khi bán thành công, có nói tới escrow) và một nhóm chợ source code (Topcode, CleanCode, Muacode, Tạp Hóa Code...). Quốc tế có Flippa, Acquire.com và nhiều sàn nhỏ. Nhận định "thị trường ngách chưa có người dẫn đầu" trong blueprint **chưa được kiểm chứng và có dấu hiệu không còn đúng**.
2. **Điểm khác biệt khả thi nằm ở lớp tin cậy, và lớp đó là thứ lfmap làm được:** một bộ công cụ chạy trên máy người bán, **mã nguồn không rời máy**, sinh ra "Hồ sơ dự án" có thể kiểm chứng (giấy phép phụ thuộc, nguồn gốc commit, mức dùng AI, test, bí mật lộ, danh mục bàn giao). Hùng đã tự làm đúng quy trình này cho 3 repo của mình (provenance, bộ hồ sơ bản quyền). Đây là lợi thế thật, khó sao chép nhanh hơn một trang đăng tin.
3. **Khuyến nghị: phương án B, "công cụ trước, sàn sau".** Bắt đầu bằng bộ công cụ Hồ sơ dự án (là plugin lfmap đóng gói, khớp Phase 3) và một danh mục tuyển chọn do Hùng tự ghép nối bằng tay. Chỉ xây nền tảng web khi đã có 3 đến 5 giao dịch làm tay thành công.
4. **Xung đột với lập trường hiện tại, nói thẳng:** nền tảng marketplace là một sản phẩm web đa người dùng trên cloud, **không dùng lại lõi lfmap** (local-first, một người dùng). Nó là dòng sản phẩm thứ hai, trái nguyên tắc solo-maintainable nếu làm song song, và trái mốc "thương mại hoá bàn ở Phase 3, lõi trước". Vì vậy: **không viết dòng code nào cho marketplace trước khi Phase 2 đạt Exit criteria.** Trước mốc đó chỉ làm kiểm chứng không cần code, tối đa khoảng 2 giờ mỗi tuần.
5. **Thành lập doanh nghiệp: muộn nhất có thể, nhưng bắt buộc trước khi mở alpha công khai.** Theo Luật Thương mại điện tử 2025 (hiệu lực 01/7/2026), chủ quản nền tảng trung gian phải là pháp nhân và đăng ký trước khi vận hành [đã tra, cần luật sư xác nhận]. Blueprint ghi "đăng ký khi bước vào giai đoạn thương mại hoá" là **quá muộn** theo luật mới. Ngược lại lập công ty quá sớm thì đốt đồng hồ ưu đãi thuế 3 năm và tốn chi phí kế toán khi chưa có doanh thu.
6. **Blueprint dẫn văn bản đã hết hiệu lực:** Nghị định 13/2023 đã được thay bằng Luật Bảo vệ dữ liệu cá nhân 2025 và Nghị định 356/2025 từ 01/01/2026 [đã tra].
7. **"Bong bóng AI vừa vỡ":** dữ kiện tra được là phiên bán tháo ngày 05/11/2026 (Nasdaq giảm 5,5%, chỉ số chip giảm 12,3%); giới bình luận còn chia rẽ là vỡ hay điều chỉnh [đã tra]. Mới 6 ngày, chưa đủ để kết luận. Kế hoạch dưới đây đúng cho cả hai kịch bản vì nó không cần vốn ngoài.
8. **AI Compute Marketplace:** giữ ở dạng ý tưởng. Sự phụ thuộc vào marketplace thứ nhất yếu hơn tài liệu tiền khả thi mô tả (mục 8).

## 2. Đánh giá thẳng bản blueprint v1.0

| Mục blueprint | Nhận xét |
| --- | --- |
| Tầm nhìn "lớn nhất Việt Nam, rồi Đông Nam Á, toàn cầu" | Chưa có căn cứ. Với một người làm, mục tiêu đúng cho 12 tháng đầu là "5 giao dịch thật", không phải thị phần. |
| "Ngách chưa có người dẫn đầu" | Chưa kiểm chứng. Đã có CoMatch và các chợ source code. Có thể chưa có ai **dẫn đầu rõ ràng**, nhưng không phải chưa có ai. Cần tự dùng thử đối thủ (mục 5.1). |
| Vấn đề của người bán | Đúng, nhưng thiếu một sự thật: phần lớn dự án dở dang **có giá trị thị trường gần bằng 0** (không người dùng, không doanh thu, code khó tiếp quản). Sàn kiếm tiền từ số ít dự án có giá trị, không phải từ số đông. |
| Vấn đề của doanh nghiệp muốn mua SaaS/ERP/CRM | Doanh nghiệp vừa và nhỏ muốn mua **phần mềm chạy được kèm hỗ trợ**, không muốn mua source code. Đây là nhu cầu khác, phục vụ bằng cách khác (bên bán tiếp tục vận hành, hoặc bên thứ ba tiếp quản). |
| Giai đoạn 2: Premium Listing 199k đến 999k/tháng | Yếu. Người bán một dự án chỉ bán **một lần**; ít ai trả phí tháng để treo một dự án đã bỏ. Phí đăng tin cố định ở các sàn quốc tế đi kèm lượng người mua lớn mà ta chưa có. |
| Giai đoạn 3: Success fee 3% đến 7% | Mức phí hợp lý so với thị trường (Acquire.com 6% đến 8%, Flippa 5% đến 10% theo nguồn bên thứ ba [đã tra]). Rủi ro chính: hai bên **rủ nhau ra ngoài sàn** (Zalo, chuyển khoản trực tiếp) để né phí. Chỉ thu được phí khi sàn cung cấp thứ bên ngoài không có: hồ sơ đã kiểm, hợp đồng mẫu, bàn giao có quy trình, giữ tiền an toàn qua ngân hàng. |
| Escrow | Không tự giữ tiền. Dịch vụ trung gian thanh toán cần giấy phép Ngân hàng Nhà nước (Nghị định 52/2024) [đã tra khung chung; việc "giữ tiền hộ" có thuộc diện này không thì chưa kiểm]. Dùng dịch vụ của ngân hàng hoặc đối tác có giấy phép. |
| KPI: 100 dự án, 300 thành viên sau 6 tháng | Chỉ số phù phiếm. 100 dự án rác làm hại sàn hơn là 10 dự án đã kiểm. Đề xuất KPI thay thế ở mục 4.4. |
| Pháp lý 6.1 | Hướng đúng nhưng thời điểm sai (xem mục 7.1). |
| Pháp lý 6.2 (không thành mạng xã hội) | Đồng ý. Lưu ý thêm: tính năng Chat ở Beta cần hỏi luật sư có kéo theo nghĩa vụ nào không. |
| Pháp lý 6.3 | Văn bản đã bị thay (mục 7.2). |
| Pháp lý 6.4 (sở hữu trí tuệ) | Đúng là rủi ro cao nhất, và là chỗ tạo khác biệt (mục 3). Cam kết của người bán là chưa đủ; cần bằng chứng. |
| Tài chính | Thiếu chi phí thời gian của Hùng, kế toán, thuế, hoàn tiền/tranh chấp. "Hoà vốn ở 100 khách trả phí" dựa trên mô hình phí tháng mà ở trên đã đánh giá là yếu. |
| "Founder có kinh nghiệm công nghệ và tài chính, nền tảng ERP" | Là điểm mạnh thật cho **thẩm định phần mềm quản trị doanh nghiệp**. Nên dùng nó để chọn ngách (mục 4.1), không chỉ ghi vào SWOT. |

## 3. Câu hỏi 1: Điều gì làm nên sự khác biệt?

### 3.1 Bản đồ đối thủ

| Nhóm | Ví dụ | Họ mạnh ở đâu | Khoảng trống |
| --- | --- | --- | --- |
| Sàn quốc tế lớn | Flippa, Acquire.com | Lượng người mua toàn cầu, quy trình, escrow qua Escrow.com | Tiếng Anh, pháp lý và thanh toán nước ngoài, ưu tiên dự án có doanh thu; dự án Việt nhỏ khó nổi bật |
| Sàn quốc tế nhỏ | Microns, Little Exits, SideProjectors, TrustMRR | Phí thấp, nhận dự án nhỏ, một số nhận cả dự án chưa có doanh thu | Như trên; thẩm định mỏng |
| Sàn Việt cùng mô hình | CoMatch / CoMarket | Đúng mô hình blueprint: bán sản phẩm số, tìm đồng hành, phí khi thành công, nói có escrow | Chưa rõ quy mô, chưa rõ thẩm định sâu tới đâu, chưa rõ pháp nhân [chưa kiểm, phải tự dùng thử] |
| Chợ source code Việt | Topcode, CleanCode, Muacode, Tạp Hóa Code, CMS77, Chocode | Lượng truy cập sẵn, giá rẻ | Bán template và đồ án, bán nhiều lần cho nhiều người; **không phải chuyển nhượng độc quyền dự án có người dùng** |
| Kênh không chính thức | Nhóm Facebook, Zalo, quan hệ cá nhân | Miễn phí, nhanh, đang là nơi phần lớn giao dịch nhỏ diễn ra [chưa kiểm, suy luận] | Không có tin cậy, không hợp đồng, hay tranh chấp |
| Sàn sở hữu trí tuệ | Mark Dealer (nhãn hiệu) | Pháp lý SHTT | Không làm phần mềm |

Mức phí [đã tra, nguồn bên thứ ba, có mâu thuẫn giữa các nguồn; kiểm trang giá chính thức trước khi dùng]: Acquire.com thu người bán phí đăng 25 đến 100 USD/tháng và phí chốt 6% đến 8%; Flippa thu phí đăng từ khoảng 29 USD tới vài trăm USD và phí thành công khoảng 5% đến 10%; Little Exits khoảng 3% chia đôi.

**Kết luận:** đối thủ thật trong 12 tháng đầu không phải Flippa mà là (a) CoMatch và (b) thói quen giao dịch qua nhóm Facebook/Zalo. Muốn thắng (b) phải cho người ta thứ mà nhóm chat không có.

### 3.2 Ba hướng khác biệt, xếp theo độ khó sao chép

**D1. Hồ sơ dự án kiểm chứng được, tạo tại chỗ (khuyến nghị làm lõi).**
Người bán cài một công cụ, chạy trên máy mình, mã nguồn không gửi đi đâu. Kết quả là một bản báo cáo có chữ ký số (hoặc mã băm) mà người mua kiểm lại được:

- Danh mục giấy phép của mọi phụ thuộc; cảnh báo GPL/AGPL/giấy phép cấm thương mại (lfmap đã có `scripts/check_licenses.py` và sổ giấy phép).
- Nguồn gốc mã: ai commit, từ khi nào, tỉ lệ mã tự viết so với phụ thuộc (đã có chỉ số phụ thuộc và sổ nguồn gốc trong lfmap).
- Khai báo mức dùng AI khi viết code (Hùng đã có mẫu `ban-quyen/03_Mo_ta_su_dung_AI.md`). Sau làn sóng "vibe coding", đây là câu hỏi người mua nghiêm túc sẽ hỏi: mã do AI sinh có được bảo hộ quyền tác giả không, và người bán có thật sự hiểu mã của mình không [vấn đề pháp lý còn mở, chưa kiểm ở Việt Nam].
- Sức khoẻ kỹ thuật ở mức sự kiện, không phải ý kiến: build được không, bao nhiêu test, test có chạy qua không, có bí mật (mật khẩu, khoá API) nằm trong lịch sử git không.
- Danh mục bàn giao: tên miền, tài khoản cửa hàng ứng dụng, hạ tầng, dữ liệu người dùng (kèm cảnh báo về dữ liệu cá nhân khi chuyển giao).
- Gói lưu chiểu: ảnh chụp mã nguồn có mã băm, dùng làm bằng chứng khi đăng ký quyền tác giả và khi tranh chấp (đã có `ban-quyen/tools/make_deposit.py`).

Vì sao khó sao chép: nó cần một nền chạy local có phân quyền, có kiểm toán, có cài đặt được trên Windows. Đó chính là lfmap. Một đối thủ làm web thuần sẽ phải yêu cầu người bán tải mã lên máy chủ của họ, điều mà người bán có dự án giá trị rất ngại.

Giới hạn phải nói rõ: báo cáo **nêu sự kiện, không định giá, không bảo đảm**. Người bán gian dối vẫn có thể sửa công cụ. Giảm rủi ro bằng: người mua tự chạy lại công cụ trên bản mã nhận được trong giai đoạn thẩm định, và điều khoản hợp đồng. Không quảng cáo là "AI thẩm định" hay "bảo đảm sạch bản quyền".

**D2. Gói chuyển nhượng đúng luật Việt Nam.**
Hợp đồng chuyển nhượng quyền tác giả phần mềm, biên bản bàn giao, NDA, hướng dẫn đăng ký quyền tác giả tại Cục Bản quyền tác giả, hướng dẫn thuế chuyển nhượng. Sàn quốc tế không làm được phần này cho giao dịch giữa hai bên Việt Nam. Điểm yếu: đối thủ trong nước chép được trong vài tuần nếu thuê luật sư. Vì vậy D2 là điều kiện cần, không phải lợi thế bền.

**D3. "Tiếp sức" thay vì chỉ "bán đứt".**
Blueprint đã có ý này (tìm co-founder, tìm đội phát triển). Thêm các dạng: chuyển quyền bảo trì, chia doanh thu, bán một phần. Phù hợp với thực tế là nhiều dự án dở dang không đáng để mua đứt nhưng đáng để có người làm tiếp. Điểm yếu: CoMatch đã có mục "tìm đồng hành"; và ghép người khó đo, khó thu phí.

### 3.3 Câu định vị đề xuất

> Nơi chuyển giao dự án phần mềm **đã được kiểm chứng tại chỗ**: người mua biết chính xác mình nhận gì, người bán không phải đưa mã nguồn cho ai trước khi có thoả thuận.

Không định vị là "Flippa của Việt Nam". Câu đó mời so sánh về số lượng tin đăng, là cuộc đua ta thua chắc.

### 3.4 Ba phương án sản phẩm

| | A. Sàn đầy đủ theo blueprint | **B. Công cụ trước, sàn tuyển chọn sau (khuyến nghị)** | C. Chỉ làm công cụ, hợp tác với sàn có sẵn |
| --- | --- | --- | --- |
| Làm gì | Web marketplace: tài khoản, tin đăng, tìm kiếm, chat, KYC, thanh toán | Plugin "Hồ sơ dự án" + danh mục 10 đến 30 dự án đã kiểm, Hùng ghép nối tay; web chỉ làm khi có giao dịch thật | Plugin "Hồ sơ dự án" phát hành độc lập; báo cáo dùng được trên CoMatch, Flippa, nhóm Facebook |
| Dùng lại lfmap | Gần như không | Nhiều (plugin, bộ cài, Flows cho vận hành) | Nhiều nhất |
| Cần pháp nhân | Có, trước khi mở | Có khi mở danh mục công khai có bên thứ ba đăng; chưa cần ở bước công cụ | Chưa cần cho tới khi thu tiền |
| Gà và trứng | Nặng nhất | Nhẹ: công cụ có ích ngay cho một phía | Không có |
| Doanh thu | Phí thành công, phí đăng | Phí thành công trên giao dịch ghép tay; sau đó phí báo cáo nâng cao | Bán công cụ hoặc báo cáo; nhỏ |
| Rủi ro chính | Đốt 6 đến 12 tháng xây thứ chưa ai cần; lệch khỏi lõi | Phụ thuộc Phase 3 (đóng gói plugin, bộ cài Windows) | Trần doanh thu thấp; phụ thuộc sàn khác |
| Đường lui | Khó | Lùi về C bất cứ lúc nào | Không cần lui |

Lý do chọn B: nó là con đường duy nhất trong ba cái vừa khớp Roadmap (Phase 3: "đóng gói từng plugin như sản phẩm độc lập"), vừa cho phép dừng sớm với chi phí thấp, vừa tạo người dùng cho chính Lan Hài.

## 4. Câu hỏi 2: Thu hút và giữ chân khách hàng đầu tiên

### 4.1 Chọn một ngách hẹp trước

Marketplace chết vì loãng. Ba ngách ứng viên:

| Ngách | Người bán | Người mua | Đánh giá |
| --- | --- | --- | --- |
| N1. Phần mềm quản trị doanh nghiệp dở dang (module ERP/CRM/kho/kế toán, công cụ nội bộ) | Công ty outsourcing, nhóm freelance có sản phẩm nội bộ bỏ dở | Công ty phần mềm khác cần nền để làm tiếp; doanh nghiệp có đội IT | **Khuyến nghị.** Khớp nền ERP của Hùng nên thẩm định có trọng lượng; giá trị mỗi giao dịch cao hơn; người mua là tổ chức, ít hơn nhưng nghiêm túc hơn |
| N2. Micro-SaaS và ứng dụng di động đã có người dùng thật | Lập trình viên độc lập | Lập trình viên khác, nhà đầu tư nhỏ | Đúng mô hình Flippa; cạnh tranh trực tiếp với CoMatch và sàn quốc tế |
| N3. Dự án AI bỏ dở sau đợt điều chỉnh | Startup AI thu hẹp hoặc đóng cửa | Doanh nghiệp muốn có năng lực AI nội bộ | Nguồn cung có thể tăng nếu thị trường xấu tiếp, nhưng giá trị thật thường nằm ở dữ liệu và con người, không nằm ở code; khó thẩm định |

Chọn N1 làm chính, nhận N2 khi có. Quyết định này là của Hùng (mục 9).

### 4.2 Phía nào khan hiếm

Phía **người mua** là phía khan hiếm. Người có dự án bỏ dở thì nhiều; người sẵn sàng trả tiền thật cho mã của người khác thì ít. Vì vậy mọi việc trong 6 tháng đầu ưu tiên tìm và hiểu người mua. Blueprint đang làm ngược (KPI tính số dự án đăng).

### 4.3 Hành trình từ alpha

| Giai đoạn | Cái thu hút | Cái giữ chân | Hùng làm gì |
| --- | --- | --- | --- |
| Trước alpha (kiểm chứng, không code) | Một cuộc trò chuyện có ích: "anh/chị định xử lý dự án bỏ dở thế nào?" | Chưa cần | 15 phỏng vấn người bán, 10 phỏng vấn người mua trong ngách N1; tự đi qua quy trình của CoMatch và một sàn quốc tế với tư cách người dùng |
| Alpha kín (10 đến 20 dự án, mời từng người) | Người bán: hồ sơ dự án miễn phí, có ích kể cả khi không bán. Người mua: danh sách ngắn, cái nào cũng đã kiểm, không phải lọc rác | Người bán: được ghép với người mua thật trong 30 ngày hoặc được nói thẳng vì sao chưa có ai quan tâm. Người mua: bản tin định kỳ dự án mới đúng tiêu chí đã khai | Tự ghép nối bằng tay, có mặt trong từng cuộc trao đổi đầu, ghi lại mọi lý do từ chối |
| Alpha mở (sau 3 đến 5 giao dịch tay) | Câu chuyện giao dịch thật (có sự đồng ý của hai bên) | Quy trình bàn giao 30 ngày sau khi mua; uy tín tích luỹ của người bán và người mua | Lúc này mới xây web tối thiểu |
| Beta trở đi | Hồ sơ dự án trở thành thứ người mua đòi hỏi | Người bán chuyên nghiệp (công ty outsourcing) quay lại với dự án thứ hai, thứ ba; người mua lặp lại | Tự động hoá vận hành bằng Lan (mục 5) |

Nguyên tắc giữ chân: một người bán cá nhân chỉ bán một lần, nên **không thể giữ chân họ bằng sàn**. Giữ được ba nhóm: (1) người mua lặp lại, (2) công ty có nhiều dự án bỏ dở, (3) người dùng công cụ Hồ sơ dự án, vì công cụ có ích hằng tháng (kiểm giấy phép, kiểm bí mật lộ, lưu chiểu) kể cả khi họ không bán gì. Nhóm (3) cũng là nhóm trở thành người dùng Lan Hài.

### 4.4 Chỉ số thay cho KPI của blueprint

| Thay vì | Đo |
| --- | --- |
| Số dự án đăng | Số dự án **đã qua kiểm** và còn hiệu lực |
| Số thành viên | Số người mua đã khai ngân sách và tiêu chí |
| Lượt xem | Số cuộc trao đổi nghiêm túc trên mỗi dự án; thời gian tới đề nghị giá đầu tiên |
| Khách trả phí tháng | Số giao dịch hoàn tất; giá trị trung bình; tỉ lệ giao dịch bị kéo ra ngoài |

Điều kiện dừng (đề xuất): sau giai đoạn kiểm chứng mà không tìm được 5 người mua khai ngân sách thật, hoặc sau 6 tháng alpha kín mà không có giao dịch nào hoàn tất, thì lùi về phương án C (chỉ giữ công cụ).

## 5. Câu hỏi 3: Vai trò của Lan Hài

Lan Hài (lfmap) có **ba vai thật** và **một vai không nên gán**.

### 5.1 Vai 1: bộ công cụ Hồ sơ dự án (là sản phẩm, là điểm khác biệt)

Một hoặc vài plugin lfmap chạy trên máy người bán, theo đúng Plugin Contract: thao tác chỉ đọc trên thư mục dự án người dùng chỉ định, qua `PermissionManager`, có kiểm toán, không gọi mạng. Đầu ra là báo cáo. Đây là hiện thân của khẩu hiệu "Every Plugin is a Product" và là plugin đóng gói thương mại đầu tiên hợp lý của Phase 3.

Điều kiện trước, đều đã nằm trong kế hoạch: bộ cài Windows (#201), đóng gói plugin (Phase 3), Plugin Registry. Thứ chưa có và phải thiết kế: ký báo cáo để người mua kiểm lại được; hỗ trợ dự án không phải Python (kiểm giấy phép cho npm, Maven, NuGet...) [chưa đánh giá công sức; đây là phần phình phạm vi lớn nhất của vai này].

### 5.2 Vai 2: người vận hành hậu trường cho Hùng

Một người không thể vừa phát triển lõi vừa vận hành sàn bằng tay. LFMAP Flows làm được: nhận hồ sơ gửi qua email, kiểm đủ trường, nhắc người bán bổ sung, soạn bản tin cho người mua theo tiêu chí, nhắc lịch bàn giao; mọi việc gửi ra ngoài đều dừng chờ Hùng duyệt (đúng mô hình tầng duyệt hiện có). Đây cũng chính là loại workflow của Exit criteria Phase 2, nên là bài nghiệm thu thực tế tốt cho lõi.

Lưu ý: dữ liệu người dùng sàn là dữ liệu cá nhân của người khác. Xử lý local là đúng hướng, nhưng nghĩa vụ theo Luật Bảo vệ dữ liệu cá nhân vẫn áp dụng, và lớp dữ liệu (ADR-025) phải xếp chúng từ `private` trở lên.

### 5.3 Vai 3: kênh phân phối hai chiều

Mỗi người bán cài công cụ Hồ sơ dự án là một người cài lfmap. Marketplace vì vậy là kênh đưa Lan Hài tới đúng nhóm người dùng đầu tiên dễ tính nhất: lập trình viên. Ngược lại, người dùng Lan Hài là nguồn người bán và người mua. Đây là lý do chiến lược mạnh nhất để hai sản phẩm đi cùng nhau.

### 5.4 Vai về sau: Lan trợ lý cho người mua và người bán

"Lan, tìm cho tôi dự án quản lý kho dưới 200 triệu, không dính GPL" là mức L2 trở lên trong phác thảo Lan Hài, tức sau Phase 3. Không hứa trong alpha.

### 5.5 Vai không nên gán: Lan Hài không phải là nền tảng marketplace

- Nền tảng web là hệ đa người dùng trên cloud: tài khoản, phân quyền nhiều người, cơ sở dữ liệu máy chủ, chống lạm dụng. Các ADR của lfmap (local-first, một người dùng, không microservice) không thiết kế cho việc này. **Nó phải là repo riêng, kiến trúc riêng, ADR riêng.**
- Không đặt tên sàn là "Lan Hài" khi chưa tra nhãn hiệu; chủ đề thương hiệu Hùng đã hoãn tới hết Phase 2. Sàn nên có tên riêng, ghi "dùng công nghệ Lan Hài" nếu muốn.
- Không để mô hình AI định giá hay kết luận pháp lý về một dự án. Trách nhiệm pháp lý rơi vào chủ sàn.

## 6. Câu hỏi 4: Khi nào bắt đầu (SWOT trong bối cảnh thị trường AI vừa điều chỉnh)

### 6.1 Dữ kiện về "bong bóng AI"

- Ngày 05/11/2026: Nasdaq giảm 5,5%, chỉ số chip giảm 12,3%, Nvidia giảm 9,2%; là phiên tệ nhất của chứng khoán Mỹ từ tháng 4/2025 [đã tra].
- Bình luận chia rẽ: có người gọi là bong bóng "xì hơi rất nhanh" chứ chưa vỡ; có người cho rằng một phiên xấu chưa phải là vỡ vì bong bóng vỡ trong nhiều tháng [đã tra].
- Áp lực vốn rõ nhất đang ở Trung Quốc (IPO tạm dừng, định giá giảm mạnh) [đã tra]. Chưa thấy nguồn nói vốn cho startup AI Mỹ đã sụp.
- Việt Nam: một nguồn thứ cấp dẫn Tracxn cho biết vốn cổ phần cho startup tới tháng 5/2026 giảm mạnh so với cùng kỳ (28,7 triệu USD so với 227 triệu USD), trong khi báo cáo NIC/VPCA/Do Ventures lại ghi nhận hồi phục ở vòng muộn và mảng AI [đã tra, hai nguồn mâu thuẫn, chưa đối chiếu phương pháp].

Cách hiểu thận trọng: thị trường **đã điều chỉnh mạnh**, chưa chắc **đã vỡ**. Không xây kế hoạch dựa trên giả định nào trong hai.

### 6.2 SWOT viết lại

| | Nội dung |
| --- | --- |
| **Điểm mạnh** | (1) Có sẵn nền local-first có phân quyền và kiểm toán để làm công cụ thẩm định tại chỗ. (2) Hùng đã tự làm trọn quy trình nguồn gốc mã và hồ sơ bản quyền, nên hiểu bài toán từ phía người bán. (3) Nền ERP và tài chính giúp thẩm định phần mềm quản trị. (4) Chi phí cố định gần bằng 0: không vốn vay, không nhân sự, nên chịu được thị trường xấu lâu. |
| **Điểm yếu** | (1) Một người, không phải lập trình viên chuyên nghiệp, quỹ thời gian và hạn mức AI đã dùng hết cho lõi. (2) Chưa có cộng đồng, chưa có người mua nào. (3) Lõi lfmap chưa xong Phase 2; công cụ khác biệt phụ thuộc Phase 3. (4) Chưa có pháp nhân; đang là người lao động của một công ty khác (cần kiểm hợp đồng lao động, mục 7.4). (5) Sàn web là năng lực khác hẳn những gì đã xây. |
| **Cơ hội** | (1) Nếu vốn co lại, số dự án và startup bỏ dở tăng: nguồn cung dồi dào. (2) Làn sóng ứng dụng viết bằng AI làm tăng nhu cầu kiểm chứng "mã này của ai, có sạch không". (3) Luật Thương mại điện tử 2025 buộc định danh người bán, làm kênh Facebook/Zalo kém hấp dẫn hơn cho giao dịch nghiêm túc và nâng rào cản cho đối thủ làm ẩu. (4) Ưu đãi cho doanh nghiệp nhỏ mới lập (Nghị quyết 198/2025) [đã tra, điều kiện cụ thể chưa kiểm]. (5) Sàn quốc tế không phục vụ tốt giao dịch nội địa bằng tiếng Việt. |
| **Thách thức** | (1) Cùng lúc cung tăng thì **cầu giảm**: người mua giữ tiền, giá giao dịch thấp, phí thu được nhỏ. (2) CoMatch đã đi trước; chợ source code có sẵn lượng truy cập. (3) Rủi ro sở hữu trí tuệ và tranh chấp rơi vào chủ sàn; câu hỏi bản quyền của mã do AI sinh còn mở. (4) Chi phí tuân thủ tăng (đăng ký nền tảng, định danh người bán, dữ liệu cá nhân). (5) Giá dịch vụ AI có thể tăng nếu các hãng ngừng bù lỗ [suy luận, chưa kiểm], ảnh hưởng tới chính việc phát triển lfmap. (6) Giao dịch bị kéo ra ngoài sàn. |

Nhận định chung: thị trường điều chỉnh **có lợi cho phía cung, bất lợi cho phía cầu và doanh thu**. Nó ủng hộ việc đi chậm, chi phí thấp, tập trung vào tin cậy; nó không ủng hộ việc bỏ vốn xây sàn lớn ngay.

### 6.3 Ước lượng độ lớn (minh hoạ, không phải dự báo)

Giả sử phí thành công 5%:

| Giá trị giao dịch trung bình | Phí mỗi giao dịch | Số giao dịch mỗi tháng để có 15 triệu đồng |
| --- | --- | --- |
| 50 triệu đồng | 2,5 triệu đồng | 6 |
| 200 triệu đồng | 10 triệu đồng | 1,5 |
| 1 tỉ đồng | 50 triệu đồng | 0,3 |

Giá trị giao dịch trung bình ở Việt Nam là con số **chưa ai biết** [chưa kiểm]; phỏng vấn ở giai đoạn kiểm chứng phải trả lời được. Bảng này cho thấy vì sao ngách N1 (giao dịch lớn, ít) hợp với một người hơn N2 (giao dịch nhỏ, nhiều).

### 6.4 Lịch theo cổng (theo kết quả, không theo ngày, giống Roadmap)

| Chặng | Điều kiện bắt đầu | Việc làm | Cổng để đi tiếp |
| --- | --- | --- | --- |
| **0. Kiểm chứng không code** | Ngay khi Hùng đồng ý; tối đa khoảng 2 giờ mỗi tuần; không dùng hạn mức AI của lõi | Phỏng vấn 15 người bán và 10 người mua; tự dùng thử CoMatch, một chợ source code, một sàn quốc tế; một buổi hỏi luật sư (mục 7.4); ghi lại giá trị giao dịch thực tế nghe được | Có ít nhất 10 người bán có dự án thật sẵn sàng đưa ra, 5 người mua khai ngân sách, và 1 cặp sẵn sàng giao dịch thử |
| **1. Công cụ Hồ sơ dự án** | Phase 2 đạt Exit criteria; cổng chặng 0 đạt | Thiết kế và làm plugin như hạng mục Phase 3; thử trên chính 3 repo của Hùng rồi trên dự án của 3 đến 5 người bán thân quen | 5 người ngoài chạy được công cụ không cần Hùng hỗ trợ; ít nhất 1 người mua nói báo cáo làm họ tin hơn |
| **2. Alpha kín, ghép tay** | Cổng chặng 1 đạt; đã lập pháp nhân và hoàn tất thủ tục theo ý kiến luật sư | 10 đến 20 dự án đã kiểm; Hùng tự ghép nối; phí chỉ thu khi thành công | 3 đến 5 giao dịch hoàn tất; tỉ lệ kéo ra ngoài chấp nhận được |
| **3. Nền tảng web tối thiểu** | Cổng chặng 2 đạt | Repo riêng; chỉ gồm tin đăng đã kiểm, tìm kiếm, liên hệ; chưa chat, chưa thanh toán trong sàn | Theo kế hoạch riêng lúc đó |

Trả lời ngắn cho "khi nào": **chặng 0 có thể bắt đầu ngay vì nó không lấy gì của lõi; mọi thứ cần code chờ sau Phase 2.** Nếu thị trường xấu kéo dài, lịch này không đổi; nếu thị trường hồi nhanh, cũng không cần chạy theo vì lợi thế của ta không nằm ở tốc độ.

## 7. Câu hỏi 5: Thành lập doanh nghiệp khi nào, cạnh tranh thế nào

### 7.1 Nghĩa vụ kéo theo thời điểm lập pháp nhân

- Luật Thương mại điện tử số 122/2025/QH15, thông qua 10/12/2025, hiệu lực 01/7/2026; Nghị định 248/2026/NĐ-CP hướng dẫn, hiệu lực cùng ngày [đã tra].
- Luật định nghĩa nền tảng thương mại điện tử trung gian là nền tảng cho phép tổ chức, cá nhân khác đăng ký tài khoản để giới thiệu, bán hàng hoá hoặc cung ứng dịch vụ [đã tra]. Một trang cho người khác đăng bán dự án phần mềm có khả năng cao rơi vào định nghĩa này [suy luận, cần luật sư].
- Chủ quản nền tảng trung gian phải là pháp nhân và đăng ký trước khi vận hành; Bộ Công Thương xác nhận đăng ký [đã tra qua bản tổng hợp từ thuvienphapluat, chưa đọc điều khoản gốc].
- Chủ quản phải xác thực điện tử danh tính người bán; một số nguồn ghi nghĩa vụ này áp dụng từ 01/01/2027, nguồn khác ghi từ 01/7/2026 [đã tra, mâu thuẫn].
- Hộ kinh doanh không phải pháp nhân [chưa kiểm lại, kiến thức chung về Bộ luật Dân sự], nên hình thức phù hợp nhỏ nhất là công ty TNHH một thành viên.

Hệ quả: **không được mở trang cho bên thứ ba tự đăng tin trước khi có công ty và đăng ký xong.** Điều này khác với blueprint.

### 7.2 Dữ liệu cá nhân

- Luật Bảo vệ dữ liệu cá nhân số 91/2025/QH15, hiệu lực 01/01/2026; Nghị định 356/2025/NĐ-CP hướng dẫn và thay hoàn toàn Nghị định 13/2023 [đã tra].
- Có quy định giãn một số nghĩa vụ trong 5 năm cho doanh nghiệp nhỏ và doanh nghiệp khởi nghiệp; hộ kinh doanh và doanh nghiệp siêu nhỏ được miễn một số nghĩa vụ, trừ khi kinh doanh dịch vụ xử lý dữ liệu hoặc xử lý dữ liệu nhạy cảm [đã tra, phạm vi miễn trừ các nguồn mô tả khác nhau].
- Thiết kế nên theo: không lưu ảnh giấy tờ tuỳ thân; định danh qua dịch vụ có sẵn (VNeID hoặc nhà cung cấp eKYC) và chỉ lưu kết quả [đề xuất, chưa kiểm tính khả dụng cho doanh nghiệp nhỏ].

### 7.3 Thuế và ưu đãi

- Nghị quyết 198/2025/QH15: miễn thuế thu nhập doanh nghiệp 3 năm cho doanh nghiệp nhỏ và vừa **tính từ ngày được cấp giấy chứng nhận đăng ký doanh nghiệp lần đầu**; Nghị định 20/2026 hướng dẫn [đã tra, điều kiện áp dụng chưa kiểm]. Hệ quả: lập công ty khi chưa có doanh thu là tiêu phí đồng hồ 3 năm.
- Nhiều nguồn ghi lệ phí môn bài bãi bỏ từ 01/01/2026 [đã tra, có một nguồn mô tả khác, cần kiểm văn bản gốc].
- Sàn có chức năng thanh toán có thể phải khấu trừ, nộp thuế thay người bán [chưa kiểm, từ trí nhớ về Nghị định 117/2025]. Thêm một lý do để chặng đầu không xử lý thanh toán trong sàn.
- Thanh toán: không tự giữ tiền của người mua (mục 2, dòng Escrow).

### 7.4 Thời điểm đề xuất và câu hỏi cho luật sư

**Thời điểm:** lập công ty TNHH một thành viên khi đồng thời có (a) cổng chặng 0 đạt, (b) công cụ Hồ sơ dự án chạy được với người ngoài, (c) sắp mở alpha kín. Trước đó Hùng làm việc với tư cách cá nhân: phỏng vấn, phát hành công cụ miễn phí, không vận hành nền tảng, không thu tiền.

Ba lựa chọn về thời điểm:

| | Lập ngay | **Lập ngay trước alpha kín (khuyến nghị)** | Lập khi có doanh thu |
| --- | --- | --- | --- |
| Ưu | Sẵn sàng pháp lý | Đúng luật, không phí đồng hồ ưu đãi, có dữ liệu thật để quyết | Rẻ nhất |
| Nhược | Phí kế toán, nghĩa vụ kê khai khi chưa có gì; đốt ưu đãi 3 năm | Phải chuẩn bị hồ sơ trước vài tuần | Có rủi ro vi phạm nếu đã vận hành nền tảng |

Câu hỏi mang đi hỏi luật sư (một buổi, trong chặng 0):

1. Danh mục tuyển chọn do tôi tự đăng thay người bán, không cho đăng ký tài khoản, có phải nền tảng trung gian theo Luật 122/2025 không?
2. Thủ tục và thời gian đăng ký nền tảng với Bộ Công Thương theo Nghị định 248/2026; nghĩa vụ xác thực người bán áp dụng từ ngày nào?
3. Tính năng nhắn tin giữa người mua và người bán có kéo theo nghĩa vụ của mạng xã hội không?
4. Giữ tiền bảo đảm giao dịch: mô hình nào hợp pháp mà không cần giấy phép trung gian thanh toán?
5. Chuyển nhượng quyền tác giả phần mềm có mã do AI sinh: rủi ro và điều khoản cần có?
6. Chuyển giao dự án có kèm dữ liệu người dùng: điều kiện theo Luật Bảo vệ dữ liệu cá nhân?
7. Hợp đồng lao động hiện tại của tôi có điều khoản hạn chế kinh doanh riêng hay quyền sở hữu sản phẩm làm ngoài giờ không?
8. Nên chuyển quyền tác giả lfmap vào công ty hay giữ ở cá nhân và cấp phép cho công ty?

Câu 8 có khuyến nghị sơ bộ: giữ quyền tác giả lõi ở cá nhân và cấp phép cho công ty, để lõi không mất theo nếu công ty đóng cửa. Câu 7 phải rõ **trước mọi hoạt động công khai**.

### 7.5 Cạnh tranh thế nào

1. **Không đua số lượng tin đăng.** Đua chất lượng kiểm chứng trong một ngách.
2. **Biến đối thủ thành kênh.** Báo cáo Hồ sơ dự án dùng được ở bất kỳ đâu, kể cả trên CoMatch, Flippa hay nhóm Facebook. Nếu nó thành thứ người mua quen đòi hỏi, mọi sàn đều quảng bá giúp.
3. **Giữ chi phí cố định gần 0** để sống lâu hơn đối thủ có vốn nhưng phải đốt tiền.
4. **Chống kéo ra ngoài bằng giá trị, không bằng cấm đoán:** hợp đồng mẫu, quy trình bàn giao, kiểm lại báo cáo, giữ tiền qua ngân hàng chỉ có khi đi qua sàn.
5. **Minh bạch về chính mình:** công khai cách kiểm, giới hạn của báo cáo, và việc chủ sàn không định giá.
6. **Sản phẩm sẽ triển khai của người khác:** Flippa hay Acquire.com hoàn toàn có thể thêm kiểm chứng tự động trên máy chủ của họ. Lợi thế còn lại của ta là "mã không rời máy" và pháp lý nội địa. Nếu hai thứ này không đủ để người dùng chọn, phương án C (chỉ công cụ) vẫn đứng được.

## 8. AI Compute Marketplace: ghi chú ngắn

Hùng xác định đây là dòng sản phẩm tương lai, sau khi marketplace thứ nhất thành công. Nhận xét ở mức ghi chú, không phải nghiên cứu đầy đủ:

- **Phần phụ thuộc là thật nhưng nhỏ:** pháp nhân, định danh, thanh toán, uy tín thương hiệu dùng lại được.
- **Phần phụ thuộc bị đánh giá quá cao:** cộng đồng người mua bán dự án không tự động là cộng đồng thuê GPU. Hai nhu cầu khác nhau; đạt 5.000 thành viên ở sàn thứ nhất không chứng minh được nhu cầu ở sàn thứ hai. Điều kiện kích hoạt nên là bằng chứng nhu cầu riêng (ví dụ danh sách chờ có đặt cọc), không phải số thành viên.
- **Cạnh tranh:** đã có các sàn GPU chia sẻ quốc tế [chưa kiểm, từ trí nhớ: Vast.ai, RunPod và các mạng tương tự]. Nếu thị trường AI tiếp tục điều chỉnh, GPU dư thừa có thể làm giá thuê giảm sâu [suy luận], thu hẹp biên của bên trung gian.
- **Độ khó:** cô lập mã và dữ liệu của người thuê trên máy của người lạ là bài toán bảo mật khó hơn mọi thứ dự án đã làm. "Phức tạp gấp 5 đến 10 lần" có thể còn là ước lượng thấp. Nó cũng đi ngược quyết định ngày 06/11 (không tự làm engine suy luận/CUDA ít nhất tới khi LFMAP hoàn thiện), ít nhất về tinh thần.
- **Điểm chạm hợp lý duy nhất với Lan Hài:** dùng chung năng lực tính toán giữa các máy **của chính người dùng** (phần đa thiết bị trong phác thảo Lan Hài). Đó là tính năng cá nhân, không phải marketplace.
- **Thứ tự trong tài liệu tiền khả thi** (Marketplace, Startup Community, Escrow, M&A, AI Compute; không làm song song) là hợp lý. Lưu ý "Startup Community" dễ trượt thành mạng xã hội, điều mà blueprint thứ nhất đã tự cảnh báo.

Đề xuất: ghi thành một Issue ý tưởng ở Backlog, không nghiên cứu thêm cho tới khi chặng 2 của marketplace thứ nhất đạt cổng.

## 9. Việc cần Hùng quyết

| # | Quyết định | Khuyến nghị |
| --- | --- | --- |
| Q1 | Chọn phương án sản phẩm A, B hay C (mục 3.4) | B |
| Q2 | Chọn ngách đầu tiên N1, N2 hay N3 (mục 4.1) | N1, nhận thêm N2 |
| Q3 | Có bắt đầu chặng 0 (kiểm chứng không code, khoảng 2 giờ mỗi tuần) ngay không | Có, với điều kiện không lấy thời gian và hạn mức của Phase 2 |
| Q4 | Có đưa "plugin Hồ sơ dự án" vào danh sách ứng viên Phase 3 không (đổi Roadmap, cần cổng của Hùng) | Có, quyết khi lập kế hoạch Phase 3 |
| Q5 | Thời điểm lập công ty (mục 7.4) | Ngay trước alpha kín |

Nếu Hùng chọn B và đồng ý chặng 0, bước kế tiếp là một file bàn giao ngắn cho chặng 0: bộ câu hỏi phỏng vấn người bán và người mua, bảng ghi kết quả, danh sách đối thủ cần tự dùng thử. Không có task code nào.

## 10. Nguồn (tra ngày 2026-11-11)

Đối thủ và mức phí:

- CoMatch: <https://comatch.vn/> (chỉ đọc qua đoạn mô tả của công cụ tìm kiếm)
- Topcode: <https://topcode.vn/gioi-thieu.htm>; CleanCode: <https://cleancode.vn/>; Muacode: <https://muacode.net/>; Tạp Hóa Code: <https://taphoacode.vn/>; CMS77: <https://cms77.io.vn/>; Chocode: <https://tinhte.vn/thread/chocode-vn-san-choi-moi-cho-anh-em-dev-muon-chia-se-kiem-tien-tu-source-code.4011155/>
- Mark Dealer: <https://markdealer.com/?page_id=3739>; VnEscrow: <https://www.vnescrow.vn/> (chưa đánh giá)
- Acquire.com: <https://help.acquire.com/how-much-does-it-cost-to-sell>, <https://acquire.com/seller-pricing>
- Flippa (bên thứ ba): <https://investors.club/flippa-fees/>, <https://www.hackceleration.com/labs/flippa-pricing>
- So sánh phí (do đối thủ viết, đọc thận trọng): <https://exitbid.io/blog/online-business-broker-fees-compared-2026>, <https://dev.to/jason_01kk/the-real-cost-of-selling-your-saas-in-2026-i-compared-every-platforms-fees-4ia3>
- Sàn nhỏ: <https://www.indiehackers.com/post/selling-a-saas-business-under-10m-in-2026-19d8aa2448>, <https://superframeworks.com/articles/best-places-sell-startup-microsaas>, <https://exitbid.io/blog/which-marketplaces-accept-pre-revenue-businesses>

Pháp lý Việt Nam:

- Luật Thương mại điện tử 122/2025/QH15: <https://thuvienphapluat.vn/van-ban/Thuong-mai/Luat-Thuong-mai-dien-tu-2025-so-122-2025-QH15-662035.aspx>
- Nghị định 248/2026/NĐ-CP: <https://dulieuphapluat.vn/van-ban/thuong-mai-van-ban/nghi-dinh-2482026nd-cp-huong-dan-luat-thuong-mai-dien-tu-1389723.html>, <https://moit.gov.vn/tin-tuc/bo-cong-thuong-pho-bien-luat-thuong-mai-dien-tu-va-nghi-dinh-so-248-2026-nd-cp.html>, <https://luatquanghuy.vn/van-ban-phap-luat-moi/thuong-mai-dien-tu-nghi-dinh-248-2026-nd-cp-co-hieu-luc-tu-01-7-2026/>
- Xác thực người bán: <https://tapchicongthuong.vn/q-a-ve-luat-thuong-mai-dien-tu-va-nghi-dinh-248--nguoi-ban-tren-san-thuong-mai-dien-tu-se-duoc-xac-thuc-danh-tinh-nhu-the-nao-531935.htm>
- Luật Bảo vệ dữ liệu cá nhân 91/2025/QH15 và Nghị định 356/2025: <https://www.vcci.com.vn/tin-tuc/luat-bao-ve-du-lieu-ca-nhan-luu-y-ve-hanh-lang-phap-ly-moi-cho-doanh-nghiep>, <https://thuvienphapluat.vn/van-ban/Quyen-dan-su/Nghi-dinh-356-2025-ND-CP-huong-dan-Luat-Bao-ve-du-lieu-ca-nhan-687428.aspx>
- Nghị định 52/2024 (thanh toán không dùng tiền mặt): <https://vcci.com.vn/legal-document/nghi-dinh-522024nd-cp-quy-dinh-ve-thanh-toan-khong-dung-tien-mat>
- Nghị quyết 198/2025/QH15: <https://luatvietnam.vn/thue-phi-le-phi/10-chinh-sach-moi-ve-thue-phi-theo-nghi-quyet-198-2025-qh15-565-102213-article.html>, <https://vneconomy.vn/go-vuong-dieu-kien-mien-thue-thu-nhap-3-nam-cho-doanh-nghiep-nho-va-vua.htm>, <https://thuvienphapluat.vn/banan/tin-tuc/tu-2026-chinh-thuc-cham-dut-thu-nop-le-phi-mon-bai-theo-nghi-quyet-1982025-15860>

Bối cảnh thị trường:

- Phiên 05/11/2026 và tranh luận về bong bóng: <https://www.dailymaverick.co.za/article/2026-11-10-day-of-reckoning-is-the-ai-bubble-finally-about-to-burst/>, <https://www.theglobalspy.com/2026/11/ai-stocks-lose-3-trillion-in-day-is.html>, <https://kingy.ai/blog/ai-stock-selloff-november-2026/>
- Trung Quốc: <https://startupfortune.com/chinas-ai-bubble-is-bursting-and-a-funding-crisis-now-threatens-smaller-tech-players/>
- Vốn cho startup Việt Nam 2026: <https://blog.mean.ceo/?p=7028> (dẫn Tracxn), <https://vir.com.vn/capital-concentrated-in-later-stage-startups-leaving-funding-gaps-for-early-ventures-156757.html>, <https://asianews.network/vietnams-private-capital-market-rebounds-as-ai-emerges-as-investment-magnet/>
