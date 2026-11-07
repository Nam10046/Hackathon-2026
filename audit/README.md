# SMART Service Audit — bài nộp Europress × Since AI 2026

Dữ liệu dùng trong bài là dữ liệu tổng hợp. Mọi đề xuất chỉ là **proposal — cần con người duyệt**.

## Có gì trong gói

| Phần nộp theo brief | Ở đâu |
|---|---|
| (1) Concept cân: sơ đồ, nhận diện container + sổ tare, tính tải và va đập, BOM, chi phí, lắp đặt, hiệu chuẩn, ngân sách sai số, kế hoạch kiểm chứng 6 bước | `docs/Weighing_Concept_Part1.pdf` |
| (2) Demo phần mềm chạy được + lộ trình tích hợp SMART | `run_solution.py`, `app.py` (dashboard), trang "SMART integration" |
| (3) Giá trị khách hàng + business case | `docs/Business_Case_Part2.pdf`, `business_case/` |
| Thư viện bên thứ ba và giấy phép | `THIRD_PARTY_LICENSES.md` |
| Test chống dùng dữ liệu tương lai | `tests/test_no_future_leakage.py` |

## Cách chạy (Windows)

Đặt thư mục `solution\` cạnh `Europress_SMART_Material_Value_Engine_v1.0.1\` (đã chạy `pip install -e ".[dev]"`), rồi:

```
pip install -r solution\requirements.txt
python solution\run_solution.py competition        (khoảng 4–5 phút)
python -m streamlit run solution\app.py
python -m pytest solution\tests -q                 (khoảng 20 giây, 14 test)
```

## Điểm số (bộ chấm chính thức, nhãn public dev/validation)

| Task | Baseline | Của đội (bản chính) | Ghi chú |
|---|---|---|---|
| B: macro-F1 (validation) | 0,782 | **0,820** | chọn ML/luật theo từng nhóm nhãn; nếu luôn dùng ML thì 0,831 |
| B: quickstart | 0,753 (hybrid) | **0,856** | lỗi bất ổn định đã được sửa |
| B2: điểm bảng điểm 0–100 | 67,75 | **96,28** (validation 96,98) | báo cáo chính thức: cắt dữ liệu ở cuối ngày thứ 45 sau khi hết tháng; báo cáo sơ bộ (ngày thứ 15): 94,36 |
| C2: regret trung bình € | 240,07 | **11,82** (thu được 98,9% giá trị) | quyết định chỉ dùng dữ liệu đã có tại ngày ra quyết định |

Bản v3 trước đây báo B2 96,0 và C2 2,31 €. Các con số đó cao hơn một phần **vì dùng dữ liệu tương lai** (xem bên dưới). Bản này chấp nhận điểm thấp hơn để đổi lấy kết quả đúng về mặt thời gian.

## Đối chiếu với rubric chấm Task D/E (v8)

| Tiêu chí rubric (mức 2) | Đáp ứng ở đâu |
|---|---|
| Mọi con số gắn nhãn observed / estimated / simulated / hypothetical | Chú giải nhãn ở thanh bên; nhãn trên KPI; cột `evidence_tag` cho từng finding và từng đề xuất; mỗi khối của trang truy vết |
| Truy vết đến từng dòng: job ref → phiếu cân → phiên bản hợp đồng → các dòng | Trang **7 · Lift audit trail** (5 khối nối nhau); bảng `outputs/*/trail_*.parquet` |
| Định lượng ràng buộc và độ bất định | Mỗi đề xuất có khoảng EV thấp–cao và độ phủ dữ liệu (số lượt có phiếu cân / chỉ có tấn trên hóa đơn / chỉ có số cân thiết bị / không rõ khối lượng; thiết bị có cân hay không); trạng thái weight bias MEASURED / MODEL_ESTIMATE / UNVERIFIABLE; mô phỏng chất lượng cảm biến |
| Giá và tỷ lệ áp dụng suy ra từ giá trị khách hàng, có phân tích độ nhạy | `docs/Business_Case_Part2.pdf`, `business_case/` |
| Đề xuất rõ ràng + lý do + **đường đảo ngược** | Hộp đề xuất: "View calculation", nút Approve / Reject / **Undo**, nhật ký chỉ ghi thêm (append-only) có cả dòng REVERSED (có test) |
| Nêu rõ điều chưa được chứng minh | Phần Giới hạn, các PDF |
| Trung lập; tách nguyên nhân do nhà vận hành, do thiết bị hay do dữ liệu | `causes.py`: mỗi chênh lệch cân được gán cho LOGISTICS (rác chất thêm bên cạnh, xe chở ghép), OPERATOR (tare xe cũ), DEVICE (cảm biến), NOISE hoặc UNKNOWN; dòng hóa đơn có mã gõ nhầm gán là DATA_ENTRY. Kiểm chứng trên nhãn **train**: khớp 82% nguyên nhân và 85% bên gây ra (425/528 ca tare, 44/54 ca thiết bị, 600/610 ca rác chất thêm) |

Ghi chú: đã thử dùng việc xác định nguyên nhân để bỏ các cảnh báo "không cần hành động" trong Task B. Kết quả kém đi ngay trên tập train (0,921 → 0,919), nên **không** áp dụng. Phần xác định nguyên nhân chỉ dùng để giải thích.

## Sửa lỗi ghép mã job khi tính tiền chênh lệch (v7)

Bộ phát hiện bất thường đã ghép các dòng hóa đơn mang mã job gõ nhầm (ví dụ `…0112X`) với đúng job theo hợp đồng và ngày. Nhưng bước tính tiền chênh lệch lại tra phí kỳ vọng theo **mã gõ nhầm**, nên không tìm thấy gì, coi phí kỳ vọng bằng 0 và tính **toàn bộ** tiền của dòng là tiền tính thừa. Lỗi này xảy ra ở 49/116 dòng WEIGHT_BASIS_MISMATCH. Giờ cả ba nơi (bảng điểm B2, giá trị khiếu nại trong C2, dashboard) dùng chung một hàm `flags.attach_expected` để ghép mã giống hệt bộ phát hiện. Mỗi dòng có thêm cột `calculation` giải thích bằng lời. Kết quả: B2 tăng 95,41 → 96,28; C2 giảm 12,15 € → 11,82 €.

## Dùng nhãn thế nào

- **Task B:** chỉ dùng nhãn của **giai đoạn train**, vào hai việc: huấn luyện mô hình ML của baseline, và chọn ML hay luật cho từng nhóm (train được chia theo thời gian: 2/3 đầu để học, 1/3 cuối để so sánh).
- **B2 và C2:** không có tham số nào được học từ nhãn. Đây là các quy tắc cố định; C2 dùng quy tắc định giá đã công bố.
- **Nhãn validation/dev:** chỉ dùng để **chấm điểm**, không dùng cho bất kỳ lựa chọn nào.

## Mốc thời gian của báo cáo B2

Mốc cắt dữ liệu của tháng M = thời điểm hết tháng (00:00 ngày 1 tháng sau, giờ Helsinki) + N ngày tròn. Snapshot chỉ giữ dữ liệu có thời điểm **trước** mốc này. Ví dụ tháng 1/2026:
- N = 15 (báo cáo sơ bộ): cắt lúc 16/02 00:00, nghĩa là có đủ mọi thứ phát hành đến hết ngày 15/02. Đây cũng là quy tắc bộ dữ liệu dùng để xác định tháng dev.
- N = 45 (báo cáo chính thức): cắt lúc 18/03 00:00. Một lượt thu gom lúc 23:59 ngày 31/01, nếu phiếu cân bị trễ tối đa 45 ngày, sẽ được công bố lúc 23:59 ngày 17/03 và vẫn nằm trong mốc. Phiếu trễ hơn thì không.

Ngày được tính theo **lịch Helsinki**: cộng N ngày trên lịch trước, sau đó mới gắn múi giờ. Nhờ vậy, việc đổi giờ mùa hè/mùa đông không làm lệch mốc. Bản v5 cộng N×24 giờ, nên tháng 2 bị cắt lúc 01:00 ngày 15/04, còn tháng 9 bị cắt lúc 23:00 ngày 14/11 (sớm 24 giờ). Test kiểm tra mọi tháng từ 2025 đến 2027 với cả N = 15 và N = 45. Việc sửa mốc ngày không làm đổi điểm B2: mốc tháng 2 không đổi ngày, còn tháng 9 không thuộc các tháng có nhãn dev.

## Không dùng dữ liệu tương lai: cách làm và bằng chứng

- **Snapshot as-of:** với mỗi ngày ra quyết định (C2) và mỗi ngày báo cáo tháng (B2), toàn bộ dữ liệu public được cắt theo **chính quy tắc as-of của bộ dữ liệu** (`europress_data.sdk._views`). Chỉ giữ phiếu cân đã công bố, hóa đơn đã phát hành (ẩn trạng thái khiếu nại), lượt thu gom đã xảy ra, phiên bản hợp đồng đang hiệu lực, chỉ số giá đã công bố. **Mọi** thứ được tính lại từ snapshot đó: tính lại Baseline-1, cờ hóa đơn, số tiền chênh lệch, ước lượng tare, nhóm hợp đồng tương tự (peer), tỷ lệ tính thừa của từng nhà vận hành (`snapshot.py`, `b2_causal.py`, `c2_actions.decide_causal`).
- **Cache snapshot có kiểm tra:** mỗi snapshot lưu dấu SHA-256 tính từ **nội dung** mọi file parquet đầu vào và thư mục metadata, cùng quy tắc as-of và phiên bản định dạng. Dấu này được tính lại ở mỗi lần gọi (không nhớ tạm trong tiến trình), nên nếu file bị thay ngay khi chương trình đang chạy thì vẫn phát hiện được. Test thay file trong cùng tiến trình mà **không** xóa cache thủ công.
- **Test đột biến (mutation test):** cố ý làm hỏng mọi phiếu cân, hóa đơn và số cân thiết bị công bố sau ngày quyết định, rồi kiểm tra quyết định tại ngày đó phải giữ nguyên. Kết quả: test đạt. Chạy cùng phép thử trên bộ competition: cách làm của v3 có **72/639** dòng bằng chứng bị thay đổi (5 quyết định đổi theo), còn cách làm mới có **0/639**.
- **Cái giá phải trả:** tại ngày quyết định chưa biết hóa đơn nào đã bị khiếu nại, nên đề xuất khiếu nại có precision 0,56. Trên quickstart, có một case bị bỏ sót vì hóa đơn tháng 7 chưa được phát hành vào ngày 01/08.

## Các module

| File | Vai trò |
|---|---|
| `snapshot.py` | cắt dữ liệu public tại một ngày, dùng quy tắc as-of của bộ dữ liệu |
| `weight_bias.py` | sửa tare cũ của xe; mỗi tháng có trạng thái **MEASURED / MODEL_ESTIMATE / UNVERIFIABLE** và độ phủ bằng chứng; không bao giờ ghi 0% khi thiếu bằng chứng |
| `flags.py` | lọc báo động giả. Cảnh báo "chưa xuất hóa đơn" chỉ được xóa khi tìm được **đúng một** mã gõ nhầm của chính job đó (cùng hợp đồng, cùng ngày, có loại phí mà job đó phải có), và mã đó không khớp với job nào khác. Trường hợp mơ hồ chuyển sang `NEEDS_REVIEW`. Bằng chứng (id dòng hóa đơn) nằm trong `outputs/*/b_uninvoiced_reconciliation.csv`. "Biểu giá cũ" chỉ được giữ khi đơn giá trùng với một phiên bản hợp đồng cũ |
| `billing.py` | tính tiền thừa/thiếu, chỉ dựa trên các dòng có bằng chứng |
| `b_select.py` | Task B: chọn ML hay luật theo từng nhóm, chỉ dùng giai đoạn train (chia theo thời gian, 2/3 đầu để học, 1/3 cuối để so) |
| `b2_causal.py` | B2: mỗi tháng tính từ snapshot của ngày báo cáo của tháng đó |
| `c2_actions.py` | C2: định giá từng hành động bằng quy tắc định giá đã công bố, từ snapshot |
| `metrics.py` | tính €/t chỉ trên các lượt có khối lượng (có test) |
| `app.py` | dashboard. €/t chỉ tính các lượt có khối lượng; chi phí các lượt không có khối lượng hiển thị riêng. Weight bias không có bằng chứng hiện là UNVERIFIABLE |

## Giới hạn

- Dữ liệu là tổng hợp: điểm số chứng minh **phương pháp**, không chứng minh khoản tiết kiệm thật.
- Trang *Weighing accuracy* là **mô phỏng độ nhạy**, chạy trên 5.787 phiếu cân sạch. Nó không phải kiểm định phần cứng. Phần cứng cần thử trên giàn và pilot thực địa (xem file concept).
- Với các hàng UNVERIFIABLE, bộ chấm vẫn cần một con số. Hệ thống điền giá trị trung vị của các hàng có bằng chứng **trong cùng tháng** và đánh dấu `weight_bias_prior_used`. Dashboard không hiển thị giá trị này như một phép đo.
- Nút Approve/Reject chỉ lưu trong phiên làm việc (có thể tải nhật ký CSV), chưa có lưu trữ bền, phân quyền hay hoàn tác. Mỗi quyết định được khóa theo bộ ba (dataset, case_id, action) và lưu kèm bản sao của đề xuất, nên đổi dataset không làm quyết định bị gắn sang đề xuất khác (có test).
- C2 trên quickstart chỉ có 7 case: thu được 0% giá trị, vì case có giá trị duy nhất bị bỏ sót (hóa đơn chưa phát hành tại ngày quyết định). Mẫu quá nhỏ để rút ra kết luận chung, nhưng cũng không được nói là mô hình hiệu quả đồng đều trên mọi bộ dữ liệu.
- Giá bán, tỷ lệ áp dụng và tỷ lệ hiện thực hóa giá trị trong business case là giả định của đội, chưa được kiểm chứng bằng nghiên cứu khách hàng.
