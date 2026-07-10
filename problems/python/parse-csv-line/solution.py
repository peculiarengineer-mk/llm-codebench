def parse_csv_line(line):
    fields = []
    i = 0
    n = len(line)
    while True:
        if i < n and line[i] == '"':
            # quoted field
            i += 1
            buf = []
            while i < n:
                ch = line[i]
                if ch == '"':
                    if i + 1 < n and line[i + 1] == '"':
                        buf.append('"')
                        i += 2
                        continue
                    i += 1
                    break
                buf.append(ch)
                i += 1
            fields.append("".join(buf))
            # skip to comma or end
            if i < n and line[i] == ",":
                i += 1
                continue
            break
        else:
            # unquoted field
            start = i
            while i < n and line[i] != ",":
                i += 1
            fields.append(line[start:i])
            if i < n and line[i] == ",":
                i += 1
                continue
            break
    return fields
