# 데이터·모델 가중치 출처 기록

이 폴더(`data/`)는 로컬 전용이며 외부에 올리지 않는다. CC BY 4.0 출처 표기 의무가 있으므로 졸업작품 발표 자료·보고서에도 아래 출처를 적는다.

## 공개 데이터셋

### CigDet (Cigarette Detection) Dataset
| 항목 | 내용 |
| --- | --- |
| 저자 | Ali Khan |
| 출처 | Mendeley Data, v1, 2024-03-28. DOI 10.17632/6hyrr8typ7.1 — https://data.mendeley.com/datasets/6hyrr8typ7/1 |
| 라이선스 | **CC BY 4.0** (`meta.json`의 `data_licence.short_name`, `LICENSE.txt` 모두 일치. 설계서 기대값과 같음) |
| 조건 | 출처 표기, 변경 사실 표시(우리는 ROI 크롭·재분할 사용), 저자의 보증을 암시하지 않을 것 |
| 받은 날짜 | 2026-10-27 (이전 실행이 받음. 파일 시각 기준) |
| 파일 | `data/public/cigdet/CigDet_dataset.zip` 34,689,636 B, SHA-256 `ef2ab181b62e93198654a333ae82b80bf3e08eafcc53e3c865340665936bae41` (`meta.json`의 해시와 **일치함을 확인**) |
| 규모 (직접 센 값) | jpg 557장 / txt 557개. train 446 (박스 446), test 111 (박스 111). 이미지당 박스 정확히 1개 |
| 라벨 형식 | YOLO txt (`class cx cy w h`, 0~1 정규화), 클래스는 `0`(cigarette) 하나. LabelImg로 라벨링 |
| 이미지 특성 (직접 확인) | **전부 250x250 px**. 얼굴·상체 근접 사진이 대부분. 박스 크기 중앙값 = 이미지 폭의 14% x 높이의 10%, 최소 3.6% x 2.4%. 담배가 **없는** 이미지는 없음(음성 이미지 없음) |
| 사용 방식 | train/val 전용(hold-out에 쓰지 않음). `training/build_roi_dataset.py`가 포즈 모델로 입·손 ROI를 잘라 담배 박스를 ROI 좌표로 옮기고, 담배가 없는 ROI는 음성 샘플로 쓴다. 원본 train → 학습, test → 검증(pHash 중복 제거 후) |
| 한계 | 250 px 근접 사진이라 로봇 시점(1~5 m, 웹캠 640~1280 px)과 도메인이 다르다. 합격선 달성은 자체 촬영 데이터에 달려 있다(설계서 9A.2) |

### COCO 2017 (부분집합: none / 유사물 하드 네거티브)
| 항목 | 내용 |
| --- | --- |
| 출처 | COCO Consortium, https://cocodataset.org (2017). 받은 것: `annotations_trainval2017.zip` (252,907,541 B, 압축 해제 후 `instances_val2017.json`만 사용)와 val2017 이미지 개별 파일 |
| 라이선스 (annotations) | CC BY 4.0. **[추정] COCO 공식 안내에 대한 사전 지식이다. 이번 실행에서 cocodataset.org 약관 페이지를 가져와 확인하려 했으나 본문이 추출되지 않아 확인하지 못했다.** 보고서에 쓰기 전에 사람이 직접 확인할 것. json의 `info`에는 라이선스 문구가 없다 |
| 라이선스 (이미지) | **이미지별로 다르다.** Flickr 원본이며 json `licenses` 필드(직접 읽음)에 CC BY-NC-SA 2.0, BY-NC 2.0, BY-NC-ND 2.0, BY 2.0, BY-SA 2.0, BY-ND 2.0, "No known copyright restrictions", US Government Work 8종이 정의돼 있다. ND 두 종(3, 6)은 크롭·합성이 변형이라 **받지 않았다**(`fetch_coco_subset.py` BAD_LICENSES). 받은 이미지 1164장의 이미지별 라이선스 분포(manifest.json에서 직접 셈): BY-NC-SA 513, BY 311, BY-NC 206, BY-SA 132, No known restrictions 2. NC 계열이 약 62%라 **상업 이용 불가**. 이미지별 조건의 정확한 해석(예: BY의 개별 저작자 표기)은 확인하지 못했다 [추정] |
| 받은 범위 | val2017 중 사람(키 비율 30% 이상) 포함 이미지 1164장: `none` 1000장(담배류 후보 객체 없음), `similar` 164장(휴대폰 95, 칼 20, 야구방망이 18, 숟가락 18, 포크 16, 칫솔 14 -- 손/입 근처의 가는 물체). 요청은 similar 500장이었으나 조건을 만족한 것이 164장뿐이었다 |
| 이미지 ID 목록 | `data/public/coco/subset/manifest.json` (id, 파일, 카테고리, 클래스, 이미지별 license, flickr_url) |
| 받은 날짜 | 2026-10-28 (파일 시각 기준 00:37~00:39) |
| 용도 | 담배 라벨 **없음**(빈 라벨) 하드 네거티브 학습용과 합성의 배경. train/val은 이미지 ID % 10 == 0 이면 val, 나머지 train로 결정적 분할 |
| 제한 | **내부 학습 전용. 재배포 금지. 얼굴이 나온 제3자 이미지를 외부 서비스에 업로드하지 않는다(라벨링 도구·클라우드 포함).** 졸업작품 발표에는 크롭·몽타주를 싣지 않거나, 싣는다면 이미지별 라이선스와 저작자 표기를 확인한다 |
| 평가 사용 | **금지.** 평가(dev/hold-out)는 직접 촬영분만 쓴다 |

## 합성 데이터 (`data/synth/`)
| 항목 | 내용 |
| --- | --- |
| 생성 | `training/synth_copy_paste.py --n 300 --real-pos 1297 --max-ratio 0.25` (copy-paste). 담배 크롭은 **CigDet train** 이미지의 박스에서, 배경 사람은 **COCO subset의 train 분할** `none` 이미지에서 가져온다. 포즈 키포인트를 이용해 입 근처(mouth) 또는 손목 근처(hand)에 붙이고 박스 라벨을 만든다 |
| 규모 | 이미지 300장 (hand 209, mouth 91), 라벨 txt, 위치 정보 `meta.json`. 실제 양성 대비 비율 상한 0.25 |
| 라이선스 | 파생물이므로 두 원본 조건을 모두 따른다: CigDet CC BY 4.0(출처 표기) + COCO 이미지별 조건(내부 전용, NC 포함). **재배포 금지** |
| 용도 | roi_ds_v2의 **train에만** 포함(val 없음). 평가 사용 금지. 육안 점검 몽타주: `_workspace/eval_out/synth_montage.jpg` |

## 총 다운로드 용량 (직접 `du`로 측정, 2026-10-28)
`data/public` 516 MiB (528,078 KiB): cigdet 76M + coco 442M (annotations zip 242M, 해제한 annotations 20M, subset 이미지 181M). `models/` 23M(가중치, 위 표). 합성 `data/synth` 29M은 생성물이다. 3GB 상한 대비 약 17%.

## 받지 않은 공개 데이터 (사유)
| 데이터 | 사유 |
| --- | --- |
| Roboflow 계열 (`mi-privado/cigarette-detection`, `sda-vfqmd/smoking36`, `deyan-markov/cigarette-finder`) | 다운로드에 Roboflow 계정·API 키가 필요하다. 지시상 로그인·키 없이 받을 수 있는 것만 받기로 해서 **받지 않았다**. 사용자 작업 목록에 적었다 |
| 그 외 설계서가 "사용 보류/불가"로 판정한 것 | 설계서 9A.2 판정 따름 |

## 모델 가중치 (사전학습, 학습 시작점)
| 파일 | 출처 | 라이선스 | 받은 날짜 |
| --- | --- | --- | --- |
| `models/yolo11n-pose.pt` → `models/pose.onnx` (320, opset 17, 정적 배치 1) | https://github.com/ultralytics/assets/releases/download/v8.3.0/yolo11n-pose.pt (COCO 사전학습, 계정 불필요) | AGPL-3.0 (졸업작품 비공개·비상업 전제, 설계서 5.2) | 2026-10-27 |
| `models/yolo11n.pt` (담배 검출기 학습 시작점) | https://github.com/ultralytics/assets/releases/download/v8.3.0/yolo11n.pt | AGPL-3.0 (같음) | 2026-10-27 |

졸업작품 범위 밖으로 배포(공개 저장소, 상업 이용, 외부 납품)하면 AGPL 의무를 재검토해야 한다.

## 받지 않은 공개 데이터 추가 메모
COCO val2017 외 분할(train2017 이미지 18GB)은 용량 때문에 받지 않았다.

## 자체 촬영 데이터
아직 없음. 규칙은 설계서 9A.3~9A.6.
