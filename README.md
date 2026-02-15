# Kiwoom MaejipBi Strategy (Demo)

`MaejipBiStrategy`는 유통 주식수 대비 순매수 누적 비율(매집비)을 계산해 매수/매도 시그널을 생성하는 예제 구현입니다.

## 핵심 계산

- `Floating Shares = Total Shares - Major Holder Shares`
- `Net Buy Volume = Sum(Buy Volume) - Sum(Sell Volume)`
- `Maejip Ratio(%) = Net Buy Volume / Floating Shares * 100`
- `Buy Strength = Total Buy Volume / Total Sell Volume`

## 매수 조건

- `Maejip Ratio >= target_ratio` (기본 5%)
- `Buy Strength >= 3.0`
- `현재가 > 20일 이동평균`

## 매도 조건

- `현재가 < 평균매수가 * 0.95`

## 실행 예시

```bash
python maejipbi_strategy.py
```

## 테스트

```bash
pytest -q
```
