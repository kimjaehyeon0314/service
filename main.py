from bs4 import BeautifulSoup
import requests
from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.responses import HTMLResponse
import pdfplumber
import re
import os
from tempfile import NamedTemporaryFile

app = FastAPI()


def extract_name_and_issuance_number(page_text):
    # 성명 추출 (예: 성 명 : 김재현)
    name_match = re.search(r"성\s*명\s*:\s*(\S+)", page_text)
    name = name_match.group(1).strip() if name_match else "Not Found"

    # 발급번호 추출 (예: 발급번호:2024830141465_81617058)
    issuance_number_match = re.search(r"발급번호\s*:\s*(\S+)", page_text)
    issuance_number = (
        issuance_number_match.group(1).strip() if issuance_number_match else "Not Found"
    )

    return name, issuance_number


def extract_information_from_pdf(pdf_path):
    with pdfplumber.open(pdf_path) as pdf:
        text_data = [page.extract_text() for page in pdf.pages]

    if len(text_data) > 1:
        # 페이지 1에서 성명과 발급번호 추출
        page_1_text = text_data[0]
        name, issuance_number = extract_name_and_issuance_number(page_1_text)

        # 페이지 2의 텍스트를 추출
        page_2_text = text_data[1]
        extracted_info = extract_information_from_page(page_2_text)

        return name, issuance_number, extracted_info
    return "Not Found", "Not Found", []


def extract_information_from_page(page_text):
    activity_periods = re.findall(r"(\d{4}년\d{1,2}월\d{1,2}일)", page_text)
    activity_times = re.findall(r"(\d+시간\d+분)", page_text)
    contents = re.findall(r"기타>(.*)\n", page_text)

    contents = [
        content.strip().replace(" ", "").replace("기타", "") for content in contents
    ]

    return [
        {
            "내용": content,
            "활동기간": normalize_date(activity_period),
            "봉사시간": activity_time,
        }
        for activity_period, activity_time, content in zip(
            activity_periods, activity_times, contents
        )
    ]


def normalize_date(date_str):
    match = re.match(r"(\d{4})년(\d{1,2})월(\d{1,2})일", date_str)
    if match:
        year, month, day = match.groups()
        return f"{year}.{int(month):02}.{int(day):02}"
    return date_str


def fetch_confirmation_data(name, issuance_number):
    url = "https://www.1365.go.kr/vols/P9330/srvcgud/cnfrmnIssu.do"

    headers = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Accept-Language": "ko-KR,ko;q=0.9",
        "Connection": "keep-alive",
        "Content-Length": "79",
        "Content-Type": "application/x-www-form-urlencoded",
        "Cookie": "mykeyword=%5E%25%uC2E4%uC801%uD655%uC778%uC11C%20%uBC1C%uAE09; wcs_bt=15c14193157a9d0:1724992747; NetFunnel_ID=; JSESSIONID=OhHe6rxPb0u9JWkB15UM8Rs6.node10; WMONID=gVzIpzXQP9s",
        "Host": "www.1365.go.kr",
        "Origin": "https://www.1365.go.kr",
        "Referer": "https://www.1365.go.kr/vols/P9330/srvcgud/cnfrmnIssu.do",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "same-origin",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
    }

    data = {"cPage": "1", "schVltrNm": name, "schIssuNo": issuance_number}

    response = requests.post(url, headers=headers, data=data)

    if response.status_code == 200:
        return response.text
    else:
        return f"Request failed with status code {response.status_code}"


def extract_and_convert_to_json(html_content):
    soup = BeautifulSoup(html_content, "html.parser")

    specific_divs = soup.find_all("div", class_=["board_list", "board_list2", "non_su"])
    results = []

    for div in specific_divs:
        li_elements = div.find_all("li")
        for li in li_elements:
            entry = {}
            entry["내용"] = li.find("dt", class_="tit_board_list").get_text(strip=True)

            dd_element = li.find("dd", class_="board_data normal")
            details = dd_element.find_all("dl")
            for detail in details:
                dt_text = detail.find("dt").get_text(strip=True).strip("[]")
                dd_text = detail.find("dd").get_text(strip=True)
                entry[dt_text] = dd_text

            entry.pop("발급일", None)

            results.append(entry)

    for result in results:
        for key in result:
            result[key] = normalize_string(result[key])

    return results


def normalize_string(text):
    return text.replace(" ", "").replace("\n", "").strip()


def compare_extracted_info(extracted_info_list, reference_info_list):
    if len(extracted_info_list) != len(reference_info_list):
        return f"Mismatch in number of records: Extracted({len(extracted_info_list)}) != Reference({len(reference_info_list)})"

    for extracted_info, reference_info in zip(extracted_info_list, reference_info_list):
        for key in reference_info:
            extracted_value = normalize_string(extracted_info.get(key, ""))
            reference_value = normalize_string(reference_info.get(key, ""))
            if extracted_value != reference_value:
                return f"Mismatch in {key}: Extracted({extracted_value}) != Reference({reference_value})"
    return "일치합니다."


@app.post("/upload/")
async def upload_pdf(file: UploadFile = File(...)):
    try:
        with NamedTemporaryFile(delete=False, suffix=".pdf") as temp_file:
            temp_file.write(file.file.read())
            temp_file_path = temp_file.name

        name, issuance_number, extracted_info_list = extract_information_from_pdf(
            temp_file_path
        )

        os.remove(temp_file_path)

        if name == "Not Found" or issuance_number == "Not Found":
            return HTMLResponse(
                content="PDF에서 성명 또는 발급번호를 추출할 수 없습니다.",
                status_code=400,
            )

        result = fetch_confirmation_data(name, issuance_number)
        reference_info_list = extract_and_convert_to_json(result)

        comparison_result = compare_extracted_info(
            extracted_info_list, reference_info_list
        )

        html_content = f"""
        <!DOCTYPE html>
        <html lang="ko">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>PDF Upload Results</title>
            <style>
                body {{
                    font-family: Arial, sans-serif;
                    background-color: #f4f4f4;
                    margin: 0;
                    padding: 0;
                    display: flex;
                    justify-content: center;
                    align-items: center;
                    height: 100vh;
                }}
                .container {{
                    background-color: #ffffff;
                    padding: 20px;
                    border-radius: 8px;
                    box-shadow: 0 0 10px rgba(0, 0, 0, 0.1);
                    text-align: left;
                }}
                h1 {{
                    color: #333;
                }}
                .info {{
                    margin-bottom: 20px;
                }}
                .comparison {{
                    font-weight: bold;
                }}
                table {{
                    width: 100%;
                    border-collapse: collapse;
                }}
                th, td {{
                    padding: 8px;
                    border: 1px solid #ddd;
                    text-align: left;
                }}
                th {{
                    background-color: #f2f2f2;
                }}
            </style>
        </head>
        <body>
            <div class="container">
                <h1>비교 결과</h1>
                <div class="info">
                    <h2>PDF:</h2>
                    <table>
                        <tr><th>내용</th><th>활동기간</th><th>봉사시간</th></tr>
                        {''.join(f'<tr><td>{item["내용"]}</td><td>{item["활동기간"]}</td><td>{item["봉사시간"]}</td></tr>' for item in extracted_info_list)}
                    </table>
                </div>
                <div class="info">
                    <h2>1365:</h2>
                    <table>
                        <tr><th>내용</th><th>활동기간</th><th>봉사시간</th></tr>
                        {''.join(f'<tr><td>{item["내용"]}</td><td>{item["활동기간"]}</td><td>{item["봉사시간"]}</td></tr>' for item in reference_info_list)}
                    </table>
                </div>
                <div class="comparison">
                    <p>비교 결과: {comparison_result}</p>
                </div>
            </div>
        </body>
        </html>
        """

        return HTMLResponse(content=html_content)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/", response_class=HTMLResponse)
async def main():
    content = """
    <!DOCTYPE html>
    <html lang="ko">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>PDF Upload</title>
        <style>
            body {
                font-family: Arial, sans-serif;
                background-color: #f4f4f4;
                margin: 0;
                padding: 0;
                display: flex;
                justify-content: center;
                align-items: center;
                height: 100vh;
            }
            .container {
                background-color: #ffffff;
                padding: 20px;
                border-radius: 8px;
                box-shadow: 0 0 10px rgba(0, 0, 0, 0.1);
                text-align: center;
            }
            h1 {
                color: #333;
            }
            input[type="file"] {
                margin: 20px 0;
            }
            input[type="submit"] {
                background-color: #4CAF50;
                color: white;
                padding: 10px 20px;
                border: none;
                border-radius: 4px;
                cursor: pointer;
            }
            input[type="submit"]:hover {
                background-color: #45a049;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>Upload PDF</h1>
            <form action="/upload/" enctype="multipart/form-data" method="post">
                <input name="file" type="file" required>
                <input type="submit" value="Upload PDF">
            </form>
        </div>
    </body>
    </html>
    """
    return HTMLResponse(content=content)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
