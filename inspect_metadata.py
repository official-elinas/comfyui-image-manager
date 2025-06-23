import sys
import json
from PIL import Image

def inspect_metadata(filepath, output_file=None):
    """Opens an image and prints or saves its metadata."""
    
    output_lines = []

    def write_output(content):
        output_lines.append(str(content))

    try:
        with Image.open(filepath) as img:
            write_output(f"--- Metadata for {filepath} ---")
            if not img.info:
                write_output("No metadata found.")
            else:
                for key, value in img.info.items():
                    write_output(f"\n[+] Key: {key}")
                    if isinstance(value, str) and value.strip().startswith('{'):
                        try:
                            parsed_json = json.loads(value)
                            pretty_json = json.dumps(parsed_json, indent=4)
                            write_output(pretty_json)
                        except json.JSONDecodeError:
                            write_output("Value is not valid JSON, printing as raw text:")
                            write_output(value)
                    else:
                        write_output(str(value))

    except FileNotFoundError:
        write_output(f"Error: File not found at {filepath}")
    except Exception as e:
        write_output(f"An error occurred: {e}")

    # Write to file or print to console
    if output_file:
        try:
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write('\n'.join(output_lines))
            print(f"Metadata has been saved to {output_file}")
        except Exception as e:
            print(f"Error writing to file {output_file}: {e}")
    else:
        for line in output_lines:
            print(line)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python inspect_metadata.py <path_to_image> [output_file.txt]")
    else:
        image_path = sys.argv[1]
        output_path = sys.argv[2] if len(sys.argv) > 2 else None
        inspect_metadata(image_path, output_path) 