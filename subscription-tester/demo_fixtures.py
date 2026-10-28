"""Versioned local samples shared by the human Demo control and agents."""
import base64
import io
from PIL import Image,ImageDraw,ImageFont

def fixtures():
    images=[]
    for i,(color,label) in enumerate(zip(('#274c45','#3f466d','#836049'),('OPENING','SUBJECT','ENDING'))):
        image=Image.new('RGB',(640,360),color);draw=ImageDraw.Draw(image);radius=65+i*15
        draw.ellipse((320-radius,160-radius,320+radius,160+radius),fill='#a8ead5')
        font=ImageFont.load_default(size=24);draw.text((320,290),label,font=font,fill='white',anchor='ms')
        raw=io.BytesIO();image.save(raw,format='PNG')
        images.append(dict(name=f'Mock storyboard {i+1}.png',data_url='data:image/png;base64,'+base64.b64encode(raw.getvalue()).decode()))
    return dict(version=1,images=images,scene=dict(duration=5,ratio='16:9',resolution='480p',audio=True,voices=[dict(id='demo-voice',voice='eve')],prompt='Begin at <IMAGE_0>. Gently orbit <IMAGE_1> while <AUDIO_0> says "A new perspective."'))
