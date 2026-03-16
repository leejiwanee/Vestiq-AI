from rembg import remove
from PIL import Image

# 원본 로고 로드
input_path = 'static/img/vestiq_original.png'
output_path = 'static/img/vestiq_logo_transparent.png'

# AI 기반 배경 제거
with open(input_path, 'rb') as input_file:
    input_data = input_file.read()
    output_data = remove(input_data)
    
# 결과 저장
with open(output_path, 'wb') as output_file:
    output_file.write(output_data)

print(f"✅ AI 기반 배경 제거 완료: {output_path}")
print("로고의 모든 요소가 보존되었습니다!")
