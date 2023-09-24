from PIL import Image, ImageDraw, ImageFont
from lib import LCD_Config, LCD_1in44, LCD_1in3


class SimpleMenuLCD:
    def __init__(self, usersettings, args):
        self.usersettings = usersettings
        self.args = args
        self.background_color = self.usersettings.get_setting_value("background_color")
        self.text_color = self.usersettings.get_setting_value("text_color")

        fontdir = "/usr/share/fonts/truetype/freefont"
        if args.fontdir != None:
            fontdir = args.fontdir
        self.lcd_ttf = fontdir + "/FreeSansBold.ttf"

        if args.display == '1in3':
            self.LCD = LCD_1in3.LCD()
            self.font = ImageFont.truetype(fontdir + '/FreeMonoBold.ttf', self.scale(10))
        else:
            self.LCD = LCD_1in44.LCD()
            self.font = ImageFont.load_default()

        self.LCD.LCD_Init()

    def rotate_image(self, image):
        if self.args.rotatescreen != "true":
            return image
        else:
            return image.transpose(3)  # Assuming 3 is the code for the rotation you want

    def show_message(self, message):
        self.image = Image.new("RGB", (self.LCD.width, self.LCD.height), self.background_color)
        self.draw = ImageDraw.Draw(self.image)

        # Positioning the text at (2, 5) for example, you can adjust this
        self.draw.text((2, 5), message, fill=self.text_color, font=self.font)

        rotated_image = self.rotate_image(self.image)
        self.LCD.LCD_ShowImage(rotated_image, 0, 0)

    def scale(self, size):
        return int(round(size * self.LCD.font_scale))
