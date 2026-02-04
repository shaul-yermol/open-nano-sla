#!/usr/bin/env python3

import sys
import os
import numpy as np
from PIL import Image
import argparse


def grayscale_to_rgb_channels(input_path, output_path):
    """
    Convert a grayscale image (stored in RGB format) to an RGB image where
    each R, G, B channel corresponds to consecutive pixels from the original image.
    
    Args:
        input_path (str): Path to the input grayscale image (in RGB format)
        output_path (str): Path where the converted image will be saved
    """
    try:
        # Load the image
        with Image.open(input_path) as img:
            # Convert to RGB if not already
            if img.mode != 'RGB':
                img = img.convert('RGB')
            
            # Convert to numpy array
            img_array = np.array(img)
            height, width, channels = img_array.shape
            
            print(f"Input image size: {width} x {height}")
            
            # Since it's grayscale in RGB format, we can just take the red channel
            # (all channels should be the same for grayscale)
            grayscale_data = img_array[:, :, 0].flatten()
            
            # Calculate new dimensions
            # We need to group every 3 pixels into RGB channels
            total_pixels = len(grayscale_data)
            rgb_pixels = total_pixels // 3
            
            if total_pixels % 3 != 0:
                print(f"Warning: Image has {total_pixels} pixels, which is not divisible by 3.")
                print(f"Using {rgb_pixels * 3} pixels, discarding the last {total_pixels % 3} pixels.")
            
            # Reshape to group every 3 consecutive pixels
            rgb_data = grayscale_data[:rgb_pixels * 3].reshape(-1, 3)

            new_width = width // 3
            new_height = height

            # Reshape to the new image dimensions
            output_array = rgb_data.reshape(new_height, new_width, 3)
            
            # Create and save the image
            output_img = Image.fromarray(output_array.astype(np.uint8))
            output_img.save(output_path)
            
            print(f"Output image size: {new_width} x {new_height}")
            print(f"Converted {rgb_pixels} groups of 3 pixels to RGB channels")
            print(f"Image successfully saved to: {output_path}")
            
    except FileNotFoundError:
        print(f"Error: Input file '{input_path}' not found.")
        sys.exit(1)
    except Exception as e:
        print(f"Error processing image: {str(e)}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description='Convert grayscale image (in RGB format) to RGB where each channel represents consecutive pixels')
    parser.add_argument('input_image', help='Path to input grayscale image (in RGB format)')
    parser.add_argument('output_image', help='Path to output RGB image')
    
    args = parser.parse_args()
    
    # Check if input file exists
    if not os.path.exists(args.input_image):
        print(f"Error: Input file '{args.input_image}' does not exist.")
        sys.exit(1)
    
    # Create output directory if it doesn't exist
    output_dir = os.path.dirname(args.output_image)
    if output_dir and not os.path.exists(output_dir):
        os.makedirs(output_dir)
    
    # Process the image
    grayscale_to_rgb_channels(args.input_image, args.output_image)


if __name__ == "__main__":
    main()
